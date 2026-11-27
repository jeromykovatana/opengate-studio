import Foundation

private struct CreatorCLIErrorPayload: Decodable {
    let error: String?
    let message: String?
    let detail: String?
}

extension StudioBridge {
    public func gyroDiagnose(
        mp4URL: URL,
        xmlURL: URL? = nil,
        bodyId: String? = nil,
        expect: String = "open-gate"
    ) async throws -> (result: GyroDiagnosticResult, trace: CommandTrace) {
        var args = ["gyro-diagnose", mp4URL.path, "--expect", expect]
        if let xmlURL {
            args.append(contentsOf: ["--xml", xmlURL.path])
        }
        if let bodyId, !bodyId.isEmpty {
            args.append(contentsOf: ["--body", bodyId])
        }
        args.append("--json")
        return try await runCreatorCLIAndDecode(GyroDiagnosticResult.self, context: "gyro-diagnose", args: args)
    }

    public func listGyroflowPresets(
        bodyId: String? = nil
    ) async throws -> (result: GyroflowPresetListResult, trace: CommandTrace) {
        var args = ["install-gyroflow-presets", "--list-only"]
        if let bodyId, !bodyId.isEmpty {
            args.append(contentsOf: ["--body", bodyId])
        }
        args.append("--json")
        return try await runCreatorCLIAndDecode(
            GyroflowPresetListResult.self,
            context: "install-gyroflow-presets --list-only",
            args: args
        )
    }

    public func installGyroflowPresets(
        targetDir: URL? = nil,
        bodyId: String? = nil
    ) async throws -> (result: InstallGyroflowPresetsResult, trace: CommandTrace) {
        var args = ["install-gyroflow-presets"]
        if let targetDir {
            args.append(contentsOf: ["--target-dir", targetDir.path])
        }
        if let bodyId, !bodyId.isEmpty {
            args.append(contentsOf: ["--body", bodyId])
        }
        args.append("--json")
        return try await runCreatorCLIAndDecode(
            InstallGyroflowPresetsResult.self,
            context: "install-gyroflow-presets",
            args: args
        )
    }

    public func ingestBatch(
        rootDir: URL,
        expect: String = "auto",
        bodyId: String? = nil,
        recursive: Bool = true
    ) async throws -> (result: BatchIngestResult, trace: CommandTrace) {
        var args = ["ingest-batch", rootDir.path, "--expect", expect]
        if let bodyId, !bodyId.isEmpty {
            args.append(contentsOf: ["--body", bodyId])
        }
        if !recursive {
            args.append("--no-recursive")
        }
        args.append("--json")
        return try await runCreatorCLIAndDecode(BatchIngestResult.self, context: "ingest-batch", args: args)
    }

    public func generateProxies(
        inputs: [URL],
        outDir: URL,
        aspect: ProxyAspectOption = .ratio3x2,
        resolution: ProxyResolutionOption = .res1080p,
        codec: ProxyCodecOption = .h264,
        preserveGyroSidecar: Bool = true,
        dryRun: Bool = false
    ) async throws -> (result: ProxyGenerationResult, trace: CommandTrace) {
        var args = ["generate-proxies"]
        args.append(contentsOf: inputs.map(\.path))
        args.append(contentsOf: [
            "--out-dir", outDir.path,
            "--aspect", aspect.rawValue,
            "--resolution", resolution.rawValue,
            "--codec", codec.rawValue,
        ])
        if !preserveGyroSidecar {
            args.append("--no-sidecar")
        }
        if dryRun {
            args.append("--dry-run")
        }
        args.append("--json")
        return try await runCreatorCLIAndDecode(ProxyGenerationResult.self, context: "generate-proxies", args: args)
    }

    private func runCreatorCLIAndDecode<T: Decodable & Sendable>(
        _ type: T.Type,
        context: String,
        args: [String]
    ) async throws -> (result: T, trace: CommandTrace) {
        let trace = try await executeCreatorCLI(args: args)
        let stdoutData = Data(trace.stdout.utf8)

        if trace.exitCode != 0 {
            let message = Self.extractCreatorErrorMessage(stdout: trace.stdout, stderr: trace.stderr)
            throw StudioBridgeError.cliFailed(exitCode: trace.exitCode, message: message, trace: trace)
        }

        do {
            let decoded = try JSONDecoder().decode(T.self, from: stdoutData)
            return (decoded, trace)
        } catch {
            throw StudioBridgeError.invalidJSON(
                context: context,
                rawOutput: trace.stdout,
                underlyingDescription: error.localizedDescription
            )
        }
    }

    private func executeCreatorCLI(args: [String]) async throws -> CommandTrace {
        let cliPath = cliScriptURL.path
        let rootURL = repoRoot

        return try await withCheckedThrowingContinuation { continuation in
            DispatchQueue.global(qos: .userInitiated).async {
                let process = Process()
                process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
                let fullArgs = ["python3", cliPath] + args
                process.arguments = fullArgs
                process.currentDirectoryURL = rootURL

                var env = ProcessInfo.processInfo.environment
                env["PYTHONUNBUFFERED"] = "1"
                env["OPENGATE_STUDIO_ROOT"] = rootURL.path
                process.environment = env

                let stdoutPipe = Pipe()
                let stderrPipe = Pipe()
                process.standardOutput = stdoutPipe
                process.standardError = stderrPipe

                do {
                    try process.run()
                } catch {
                    continuation.resume(throwing: StudioBridgeError.processLaunchFailed(error.localizedDescription))
                    return
                }

                let group = DispatchGroup()
                var stdoutData = Data()
                var stderrData = Data()

                group.enter()
                DispatchQueue.global(qos: .utility).async {
                    stdoutData = stdoutPipe.fileHandleForReading.readDataToEndOfFile()
                    group.leave()
                }

                group.enter()
                DispatchQueue.global(qos: .utility).async {
                    stderrData = stderrPipe.fileHandleForReading.readDataToEndOfFile()
                    group.leave()
                }

                process.waitUntilExit()
                group.wait()

                let stdoutStr = String(data: stdoutData, encoding: .utf8) ?? ""
                let stderrStr = String(data: stderrData, encoding: .utf8) ?? ""
                let cmdDisplay = (["/usr/bin/env"] + fullArgs).joined(separator: " ")

                let trace = CommandTrace(
                    command: cmdDisplay,
                    exitCode: process.terminationStatus,
                    stdout: stdoutStr,
                    stderr: stderrStr
                )
                continuation.resume(returning: trace)
            }
        }
    }

    private static func extractCreatorErrorMessage(stdout: String, stderr: String) -> String {
        for raw in [stdout, stderr] {
            let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !trimmed.isEmpty else { continue }
            if let data = trimmed.data(using: .utf8),
               let payload = try? JSONDecoder().decode(CreatorCLIErrorPayload.self, from: data) {
                if let msg = payload.error ?? payload.message ?? payload.detail, !msg.isEmpty {
                    return msg
                }
            }
        }
        let combined = [
            stderr.trimmingCharacters(in: .whitespacesAndNewlines),
            stdout.trimmingCharacters(in: .whitespacesAndNewlines),
        ]
        .filter { !$0.isEmpty }
        .joined(separator: " | ")
        return combined.isEmpty ? "Unknown CLI error" : combined
    }
}
