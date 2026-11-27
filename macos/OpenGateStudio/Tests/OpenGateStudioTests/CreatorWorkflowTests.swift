import Foundation
import OpenGateStudioCore
import Testing

@Suite("OpenGateStudio Creator Workflow Tests")
struct CreatorWorkflowTests {
    private func makeBridge(sessionDir: URL? = nil) throws -> StudioBridge {
        let testFileURL = URL(fileURLWithPath: #filePath)
        let candidateRoot = testFileURL
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        if StudioBridge.isValidRepoRoot(candidateRoot) {
            return try StudioBridge(repoRoot: candidateRoot, sessionDirectory: sessionDir)
        }
        return try StudioBridge(sessionDirectory: sessionDir)
    }

    private func makeTempDir(prefix: String) throws -> URL {
        let dir = FileManager.default.temporaryDirectory
            .appendingPathComponent("\(prefix)-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }

    private func writeSynthetic3x2Clip(repoRoot: URL, mp4URL: URL, xmlURL: URL) throws {
        let py = """
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(sys.argv[1]) / "cli"))
        import bionz_clip_check as bcc
        Path(sys.argv[2]).write_bytes(bcc.build_synthetic_mp4(width=3840, height=2560, codec="hvc1"))
        Path(sys.argv[3]).write_text(bcc.build_synthetic_xml(width=3840, height=2560, codec="hvc1", aspect_ratio="3:2"), encoding="utf8")
        """
        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        proc.arguments = ["python3", "-c", py, repoRoot.path, mp4URL.path, xmlURL.path]
        let errPipe = Pipe()
        proc.standardError = errPipe
        try proc.run()
        proc.waitUntilExit()
        if proc.terminationStatus != 0 {
            let errText = String(data: errPipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
            throw NSError(domain: "CreatorWorkflowTests", code: Int(proc.terminationStatus), userInfo: [
                NSLocalizedDescriptionKey: "Failed to build synthetic 3:2 fixture: \(errText)"
            ])
        }
    }

    private func synthesizeRealTinyMP4(mp4URL: URL, xmlURL: URL, repoRoot: URL) throws {
        let ffmpegPath = FileManager.default.isExecutableFile(atPath: "/opt/homebrew/bin/ffmpeg")
            ? "/opt/homebrew/bin/ffmpeg"
            : "ffmpeg"
        let proc = Process()
        proc.executableURL = ffmpegPath.hasPrefix("/")
            ? URL(fileURLWithPath: ffmpegPath)
            : URL(fileURLWithPath: "/usr/bin/env")
        var args: [String] = ffmpegPath.hasPrefix("/") ? [] : ["ffmpeg"]
        args.append(contentsOf: [
            "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc=size=384x256:rate=24000/1001:duration=0.5",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=0.5",
            "-ac", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-timecode", "01:02:03:04",
            mp4URL.path,
        ])
        proc.arguments = args
        let errPipe = Pipe()
        proc.standardError = errPipe
        try proc.run()
        proc.waitUntilExit()
        if proc.terminationStatus != 0 {
            let errText = String(data: errPipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
            throw NSError(domain: "CreatorWorkflowTests", code: Int(proc.terminationStatus), userInfo: [
                NSLocalizedDescriptionKey: "ffmpeg failed to synthesize test clip: \(errText)"
            ])
        }

        let py = """
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(sys.argv[1]) / "cli"))
        import bionz_clip_check as bcc
        Path(sys.argv[2]).write_text(bcc.build_synthetic_xml(width=3840, height=2560, codec="hvc1", aspect_ratio="3:2"), encoding="utf8")
        """
        let xmlProc = Process()
        xmlProc.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        xmlProc.arguments = ["python3", "-c", py, repoRoot.path, xmlURL.path]
        try xmlProc.run()
        xmlProc.waitUntilExit()
        #expect(xmlProc.terminationStatus == 0)
    }

    @Test("DeliveryCropCalculator computes centered even-pixel crops and safe areas")
    func testDeliveryCropCalculator() {
        let specs4k = DeliveryCropCalculator.compute(width: 3840, height: 2560)
        #expect(specs4k.count == 4)

        let byAspect = Dictionary(uniqueKeysWithValues: specs4k.map { ($0.aspect, $0) })
        let crop16x9 = byAspect["16:9"]
        #expect(crop16x9?.width == 3840)
        #expect(crop16x9?.height == 2160)
        #expect(crop16x9?.x == 0)
        #expect(crop16x9?.y == 200)
        #expect(crop16x9?.actionSafe?.scale == 0.90)
        #expect(crop16x9?.titleSafe?.scale == 0.80)

        let crop9x16 = byAspect["9:16"]
        #expect(crop9x16?.width == 1440)
        #expect(crop9x16?.height == 2560)
        #expect(crop9x16?.x == 1200)

        let crop1x1 = byAspect["1:1"]
        #expect(crop1x1?.width == 2560)
        #expect(crop1x1?.height == 2560)

        for spec in specs4k {
            #expect(spec.width % 2 == 0)
            #expect(spec.height % 2 == 0)
            #expect(spec.normRect.width > 0 && spec.normRect.width <= 1.0)
            #expect(spec.normRect.height > 0 && spec.normRect.height <= 1.0)
        }
    }

    @Test("StudioBridge.ingestBatch scans SD-card tree and pairs *M01.XML")
    func testStudioBridgeIngestBatch() async throws {
        let tmpDir = try makeTempDir(prefix: "ogs-ingest")
        defer { try? FileManager.default.removeItem(at: tmpDir) }
        let bridge = try makeBridge(sessionDir: tmpDir)

        let clipDir = tmpDir.appendingPathComponent("PRIVATE/M4ROOT/CLIP", isDirectory: true)
        try FileManager.default.createDirectory(at: clipDir, withIntermediateDirectories: true)

        let mp4URL = clipDir.appendingPathComponent("C0001.MP4")
        let xmlURL = clipDir.appendingPathComponent("C0001M01.XML")
        try writeSynthetic3x2Clip(repoRoot: bridge.repoRoot, mp4URL: mp4URL, xmlURL: xmlURL)

        let (result, trace) = try await bridge.ingestBatch(rootDir: tmpDir, expect: "auto", recursive: true)
        #expect(trace.exitCode == 0)
        #expect(result.ok == true)
        #expect(result.clipsScanned == 1)
        #expect(result.clipsPassed == 1)
        #expect(result.clipsFailed == 0)

        let clip = try #require(result.clips.first)
        #expect(clip.filename == "C0001.MP4")
        #expect(clip.width == 3840)
        #expect(clip.height == 2560)
        #expect(clip.vprf3x2 == true)
        #expect(clip.xml3x2 == true)
        #expect(clip.rtmdGyroPresent == true)
        #expect(clip.deliveryCrops?["16:9"]?.height == 2160)
    }

    @Test("StudioBridge.generateProxies runs dry-run and real ffmpeg proxy with relink verification")
    func testStudioBridgeGenerateProxies() async throws {
        let tmpDir = try makeTempDir(prefix: "ogs-swift-proxy")
        defer { try? FileManager.default.removeItem(at: tmpDir) }
        let bridge = try makeBridge(sessionDir: tmpDir)

        let srcMP4 = tmpDir.appendingPathComponent("C0020.MP4")
        let srcXML = tmpDir.appendingPathComponent("C0020M01.XML")
        try synthesizeRealTinyMP4(mp4URL: srcMP4, xmlURL: srcXML, repoRoot: bridge.repoRoot)

        let dryDir = tmpDir.appendingPathComponent("dry_proxies", isDirectory: true)
        let (dryRes, dryTrace) = try await bridge.generateProxies(
            inputs: [srcMP4],
            outDir: dryDir,
            aspect: .ratio3x2,
            resolution: .res720p,
            codec: .h264,
            preserveGyroSidecar: true,
            dryRun: true
        )
        #expect(dryTrace.exitCode == 0)
        #expect(dryRes.ok == true)
        #expect(dryRes.dryRun == true)
        #expect(!FileManager.default.fileExists(atPath: dryDir.path))

        let outDir = tmpDir.appendingPathComponent("real_proxies", isDirectory: true)
        let (realRes, realTrace) = try await bridge.generateProxies(
            inputs: [srcMP4],
            outDir: outDir,
            aspect: .ratio3x2,
            resolution: .res720p,
            codec: .h264,
            preserveGyroSidecar: true,
            dryRun: false
        )
        #expect(realTrace.exitCode == 0)
        #expect(realRes.ok == true)
        #expect(realRes.succeededCount == 1)
        #expect(FileManager.default.fileExists(atPath: realRes.manifestPath))

        let proxy = try #require(realRes.proxies.first)
        #expect(proxy.ok == true)
        #expect(proxy.targetWidth == 1080)
        #expect(proxy.targetHeight == 720)
        #expect(proxy.sidecarCopied == true)
        #expect(proxy.rtmdPreservedInProxy == false)
        #expect(proxy.relinkToOriginalForGyro == true)
        #expect(proxy.relinkVerification.fpsMatch == true)
        #expect(proxy.relinkVerification.timecodeMatch == true)
        #expect(proxy.relinkVerification.audioChannelsMatch == true)
        #expect(proxy.relinkVerification.originalSha256Unchanged == true)
        #expect(proxy.relinkVerification.relinkOk == true)
    }

    @Test("Creator gyro diagnostic and preset JSON models decode cleanly")
    func testGyroDiagnosticAndPresetDecoding() throws {
        let diagJSON = """
        {
          "ok": true,
          "ready_for_gyroflow": true,
          "ready_for_catalyst": true,
          "body_id": "zve1_202",
          "file": "/tmp/C0001.MP4",
          "failure_category": "none",
          "summary": "All rtmd and 3:2 geometry checks passed.",
          "checks": {"rtmd_present": true, "cadence_ok": true},
          "readout_calibration": {"frame_readout_time_ms": 10.3, "evidence_level": "estimated_from_imx510_line_ratio"},
          "ibis_guidance": {"active_steadyshot": "OFF recommended"},
          "recommended_actions": []
        }
        """
        let diag = try JSONDecoder().decode(GyroDiagnosticResult.self, from: Data(diagJSON.utf8))
        #expect(diag.ok == true)
        #expect(diag.readyForGyroflow == true)
        #expect(diag.failureCategory == "none")
        #expect(diag.readoutTimeMs == 10.3)
        #expect(diag.evidenceLevel == "estimated_from_imx510_line_ratio")
        #expect(diag.checkPairs.count == 2)

        let listJSON = """
        {
          "ok": true,
          "preset_dir": "/repo/presets/gyroflow",
          "presets": [
            {
              "filename": "Sony_ZV-E1_OpenGate_3840x2560_3x2.json",
              "body_id": "zve1_202",
              "camera_model": "Sony ZV-E1",
              "dimension": "3840x2560",
              "frame_readout_time_ms": 10.3,
              "evidence_level": "estimated_from_imx510_line_ratio",
              "sha256": "abc123"
            }
          ]
        }
        """
        let list = try JSONDecoder().decode(GyroflowPresetListResult.self, from: Data(listJSON.utf8))
        #expect(list.ok == true)
        #expect(list.presets.count == 1)
        #expect(list.presets[0].evidenceLevel == "estimated_from_imx510_line_ratio")

        let installJSON = """
        {
          "ok": true,
          "target_dir": "/tmp/gyroflow_profiles",
          "installed_count": 4,
          "installed_files": ["a.json", "b.json", "c.json", "d.json"]
        }
        """
        let installed = try JSONDecoder().decode(InstallGyroflowPresetsResult.self, from: Data(installJSON.utf8))
        #expect(installed.ok == true)
        #expect(installed.installedCount == 4)
    }

    @Test("StudioBridge integrates live with studio_gyro diagnose and preset install CLIs")
    func testStudioBridgeLiveGyroIntegration() async throws {
        let tmpDir = try makeTempDir(prefix: "ogs-live-gyro")
        defer { try? FileManager.default.removeItem(at: tmpDir) }
        let bridge = try makeBridge(sessionDir: tmpDir)

        let mp4URL = tmpDir.appendingPathComponent("C0005.MP4")
        let xmlURL = tmpDir.appendingPathComponent("C0005M01.XML")
        try writeSynthetic3x2Clip(repoRoot: bridge.repoRoot, mp4URL: mp4URL, xmlURL: xmlURL)

        let (diag, diagTrace) = try await bridge.gyroDiagnose(
            mp4URL: mp4URL,
            xmlURL: xmlURL,
            bodyId: "zve1_202",
            expect: "open-gate"
        )
        #expect(diagTrace.exitCode == 0)
        #expect(diag.ok == true)
        #expect(diag.readyForGyroflow == true)
        #expect(diag.readyForCatalyst == true)
        #expect(diag.failureCategory == "none")
        #expect(diag.readoutTimeMs == 10.3)
        #expect(diag.evidenceLevel == "estimated_from_imx510_line_ratio")
        #expect(diag.checkPairs.count == 5)

        let (presetList, listTrace) = try await bridge.listGyroflowPresets()
        #expect(listTrace.exitCode == 0)
        #expect(presetList.ok == true)
        #expect(presetList.presets.count == 4)

        let targetDir = tmpDir.appendingPathComponent("gyroflow_presets", isDirectory: true)
        let (installRes, instTrace) = try await bridge.installGyroflowPresets(targetDir: targetDir)
        #expect(instTrace.exitCode == 0)
        #expect(installRes.ok == true)
        #expect(installRes.installedCount == 4)
    }
}
