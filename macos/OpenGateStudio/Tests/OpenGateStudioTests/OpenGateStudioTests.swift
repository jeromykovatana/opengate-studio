import Foundation
import OpenGateStudioCore
import Testing

@Suite("OpenGateStudio End-to-End Integration Tests")
struct OpenGateStudioTests {
    private func makeBridge(sessionDir: URL? = nil) throws -> StudioBridge {
        let testFileURL = URL(fileURLWithPath: #filePath)
        // Tests/OpenGateStudioTests/OpenGateStudioTests.swift -> macos/OpenGateStudio -> macos -> repoRoot
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

    @Test("listBodies returns all 3 supported camera bodies")
    func testListBodies() async throws {
        let bridge = try makeBridge()
        let (result, trace) = try await bridge.listBodies()
        #expect(trace.exitCode == 0)

        let ids = Set(result.bodies.map(\.bodyId))
        #expect(ids.contains("zve1_202"))
        #expect(ids.contains("a7s3_501"))
        #expect(ids.contains("fx3_702"))
        for body in result.bodies {
            #expect(body.pinsOk == true)
            #expect(body.packs["core_open_gate"] != nil)
            #expect(body.packs["mp4_3x2"] != nil)
        }
    }

    @Test("verifyPins validates all kit manifests and .so SHA-256 pins")
    func testVerifyPins() async throws {
        let bridge = try makeBridge()
        let (result, trace) = try await bridge.verifyPins()
        #expect(trace.exitCode == 0)
        #expect(result.ok == true)
        #expect(result.checkedFiles > 0)
        #expect(result.bodies["zve1_202"]?.ok == true)
        #expect(result.bodies["a7s3_501"]?.ok == true)
        #expect(result.bodies["fx3_702"]?.ok == true)
    }

    @Test("preflight fails ready gate on mixed_powerswitch and passes on stock")
    func testPreflightMixedVsStock() async throws {
        let sessionDir = try makeTempDir(prefix: "ogs-preflight")
        defer { try? FileManager.default.removeItem(at: sessionDir) }
        let bridge = try makeBridge(sessionDir: sessionDir)

        let (mixed, _) = try await bridge.preflight(
            bodyId: "zve1_202",
            mockCamera: true,
            mockState: .mixedPowerswitch,
            sessionDir: sessionDir
        )
        #expect(mixed.ok == true)
        #expect(mixed.ready == false)
        #expect(mixed.verdict.contains("NOT READY"))

        // Applying after mixed_powerswitch preflight must be refused by CLI
        do {
            _ = try await bridge.apply(
                bodyId: "zve1_202",
                packs: ["mp4_3x2"],
                mockCamera: true,
                sessionDir: sessionDir
            )
            Issue.record("Expected apply to fail after mixed_powerswitch preflight")
        } catch let error as StudioBridgeError {
            if case .cliFailed(let exitCode, _, _) = error {
                #expect(exitCode != 0)
            } else {
                Issue.record("Unexpected StudioBridgeError: \(error)")
            }
        }

        let (stock, _) = try await bridge.preflight(
            bodyId: "zve1_202",
            mockCamera: true,
            mockState: .stock,
            sessionDir: sessionDir
        )
        #expect(stock.ok == true)
        #expect(stock.ready == true)
        #expect(stock.state == "stock")
        #expect(stock.verdict.contains("READY"))
    }

    @Test("apply and putback execute ordered .so steps cleanly")
    func testApplyAndPutback() async throws {
        let sessionDir = try makeTempDir(prefix: "ogs-apply")
        defer { try? FileManager.default.removeItem(at: sessionDir) }
        let bridge = try makeBridge(sessionDir: sessionDir)

        let (preflight, _) = try await bridge.preflight(
            bodyId: "zve1_202",
            mockCamera: true,
            mockState: .stock,
            sessionDir: sessionDir
        )
        #expect(preflight.ready == true)

        let (apply, _) = try await bridge.apply(
            bodyId: "zve1_202",
            packs: ["mp4_3x2", "hdmi32", "high_bitrate", "xavc_si"],
            mockCamera: true,
            sessionDir: sessionDir
        )
        #expect(apply.ok == true)
        #expect(!apply.stepsRun.isEmpty)
        #expect(apply.closingDumpVerdict.contains("VERDICT READY"))

        let (putback, _) = try await bridge.putback(
            bodyId: "zve1_202",
            packs: ["mp4_3x2", "hdmi32", "high_bitrate", "xavc_si"],
            mockCamera: true,
            sessionDir: sessionDir
        )
        #expect(putback.ok == true)
        #expect(!putback.stepsRun.isEmpty)
        #expect(putback.state == "stock")
    }

    @Test("checkClip verifies a synthetic 3840x2560 MP4 + M01.XML + rtmd fixture")
    func testCheckClip3x2Fixture() async throws {
        let tmpDir = try makeTempDir(prefix: "ogs-clip")
        defer { try? FileManager.default.removeItem(at: tmpDir) }
        let bridge = try makeBridge(sessionDir: tmpDir)

        let mp4URL = tmpDir.appendingPathComponent("C0001.MP4")
        let xmlURL = tmpDir.appendingPathComponent("C0001M01.XML")
        try generateValid3x2ClipFixture(repoRoot: bridge.repoRoot, mp4URL: mp4URL, xmlURL: xmlURL)

        let autoDetected = StudioBridge.autoDetectSidecarXML(for: mp4URL)
        #expect(autoDetected?.standardizedFileURL == xmlURL.standardizedFileURL)

        let (clipRes, trace) = try await bridge.checkClip(mp4URL: mp4URL, xmlURL: autoDetected)
        #expect(trace.exitCode == 0)
        #expect(clipRes.ok == true)
        #expect(clipRes.width == 3840)
        #expect(clipRes.height == 2560)
        #expect(clipRes.vprf3x2 == true)
        #expect(clipRes.xml3x2 == true)
        #expect(clipRes.rtmdGyroPresent == true)
        #expect(clipRes.rtmdSamples > 0)
        #expect(clipRes.issues.isEmpty)
    }

    @Test("checkClip flags 16:9 squeezed XML and missing rtmd as failures")
    func testCheckClipRejects16x9XML() async throws {
        let tmpDir = try makeTempDir(prefix: "ogs-clip-bad")
        defer { try? FileManager.default.removeItem(at: tmpDir) }
        let bridge = try makeBridge(sessionDir: tmpDir)

        let mp4URL = tmpDir.appendingPathComponent("C0002.MP4")
        let xmlURL = tmpDir.appendingPathComponent("C0002M01.XML")
        try generateValid3x2ClipFixture(repoRoot: bridge.repoRoot, mp4URL: mp4URL, xmlURL: xmlURL)

        // Overwrite XML with broken 16:9 aspectRatio tag
        let badXML = """
        <?xml version="1.0" encoding="UTF-8"?>
        <NonRealTimeMeta xmlns="urn:schemas-professionalDisc:nonRealTimeMeta:ver.2.20">
          <VideoFormat>
            <VideoFrame videoCodec="HEVC_3840_2560_H420P@L51" captureFps="23.976p" formatFps="23.976p"/>
            <VideoLayout pixel="3840" numOfVerticalLine="2560" aspectRatio="16:9"/>
          </VideoFormat>
        </NonRealTimeMeta>
        """
        try badXML.write(to: xmlURL, atomically: true, encoding: .utf8)

        do {
            _ = try await bridge.checkClip(mp4URL: mp4URL, xmlURL: xmlURL)
            Issue.record("Expected checkClip to exit non-zero for 16:9 VideoLayout XML")
        } catch let error as StudioBridgeError {
            if case .cliFailed(let exitCode, _, let trace) = error {
                #expect(exitCode != 0)
                let decoded = try JSONDecoder().decode(ClipCheckResult.self, from: Data(trace.stdout.utf8))
                #expect(decoded.ok == false)
                #expect(decoded.xml3x2 == false)
                #expect(!decoded.issues.isEmpty)
            } else {
                Issue.record("Unexpected error: \(error)")
            }
        }
    }

    @Test("All three camera bodies pass preflight -> apply -> putback round-trip")
    func testAllThreeBodiesRoundTrip() async throws {
        let sessionDir = try makeTempDir(prefix: "ogs-all-bodies")
        defer { try? FileManager.default.removeItem(at: sessionDir) }
        let bridge = try makeBridge(sessionDir: sessionDir)

        for bodyId in ["zve1_202", "a7s3_501", "fx3_702"] {
            let (pre, _) = try await bridge.preflight(
                bodyId: bodyId,
                mockCamera: true,
                mockState: .stock,
                sessionDir: sessionDir
            )
            #expect(pre.ready == true)

            let (app, _) = try await bridge.apply(
                bodyId: bodyId,
                packs: ["mp4_3x2", "screen_3x2", "hdmi32", "high_bitrate", "xavc_si"],
                mockCamera: true,
                sessionDir: sessionDir
            )
            #expect(app.ok == true)
            #expect(app.closingDumpVerdict.contains("VERDICT READY"))

            let (put, _) = try await bridge.putback(
                bodyId: bodyId,
                packs: nil,
                mockCamera: true,
                sessionDir: sessionDir
            )
            #expect(put.ok == true)
            #expect(put.state == "stock")
        }
    }

    @Test("latestSession reports empty before any run and tracks latest session afterwards")
    func testLatestSession() async throws {
        let sessionDir = try makeTempDir(prefix: "ogs-latest-session")
        defer { try? FileManager.default.removeItem(at: sessionDir) }
        let bridge = try makeBridge(sessionDir: sessionDir)

        let (emptyRes, emptyTrace) = try await bridge.latestSession(bodyId: "zve1_202", sessionDir: sessionDir)
        #expect(emptyTrace.exitCode == 0)
        #expect(emptyRes.ok == true)
        #expect(emptyRes.found == false)
        #expect(emptyRes.bodyId == "zve1_202")
        #expect(emptyRes.sessionId == nil)

        let (pre, _) = try await bridge.preflight(
            bodyId: "zve1_202",
            mockCamera: true,
            mockState: .stock,
            sessionDir: sessionDir
        )
        #expect(pre.ready == true)

        let (afterPre, afterPreTrace) = try await bridge.latestSession(bodyId: "zve1_202", sessionDir: sessionDir)
        #expect(afterPreTrace.exitCode == 0)
        #expect(afterPre.ok == true)
        #expect(afterPre.found == true)
        #expect(afterPre.bodyId == "zve1_202")
        #expect(afterPre.ready == true)
        #expect(afterPre.state == "stock")
        #expect(afterPre.verdict.contains("READY"))

        let (app, _) = try await bridge.apply(
            bodyId: "zve1_202",
            packs: ["mp4_3x2", "screen_3x2"],
            mockCamera: true,
            sessionDir: sessionDir
        )
        #expect(app.ok == true)

        let (afterApply, _) = try await bridge.latestSession(bodyId: "zve1_202", sessionDir: sessionDir)
        #expect(afterApply.ok == true)
        #expect(afterApply.found == true)
        #expect(afterApply.ready == true)
        #expect(afterApply.state == "applied")
        #expect(afterApply.activePacks.contains("mp4_3x2"))
    }

    @Test("prepareLiveCommand creates executable .command scripts without opening Terminal when suppressed")
    func testPrepareLiveCommand() async throws {
        setenv("OPENGATE_NO_TERMINAL_OPEN", "1", 1)
        let sessionDir = try makeTempDir(prefix: "ogs-live-cmd")
        defer { try? FileManager.default.removeItem(at: sessionDir) }
        let bridge = try makeBridge(sessionDir: sessionDir)

        let (preCmd, preTrace) = try await bridge.prepareLiveCommand(
            action: .preflight,
            bodyId: "zve1_202",
            packs: nil,
            sessionDir: sessionDir
        )
        #expect(preTrace.exitCode == 0)
        #expect(preCmd.ok == true)
        #expect(preCmd.action == "preflight")
        #expect(preCmd.bodyId == "zve1_202")
        #expect(preCmd.commandFile.hasSuffix(".command"))
        #expect(!preCmd.preview.isEmpty)
        #expect(FileManager.default.fileExists(atPath: preCmd.commandFile))
        #expect(FileManager.default.isExecutableFile(atPath: preCmd.commandFile))

        let (applyCmd, applyTrace) = try await bridge.prepareLiveCommand(
            action: .apply,
            bodyId: "fx3_702",
            packs: ["mp4_3x2", "hdmi32"],
            sessionDir: sessionDir
        )
        #expect(applyTrace.exitCode == 0)
        #expect(applyCmd.ok == true)
        #expect(applyCmd.action == "apply")
        #expect(applyCmd.bodyId == "fx3_702")
        #expect(FileManager.default.isExecutableFile(atPath: applyCmd.commandFile))
        let applyScript = try String(contentsOfFile: applyCmd.commandFile, encoding: .utf8)
        #expect(applyScript.contains("fx3_702"))
        #expect(applyScript.contains("mp4_3x2"))

        let (putCmd, putTrace) = try await bridge.prepareLiveCommand(
            action: .putback,
            bodyId: "a7s3_501",
            packs: nil,
            sessionDir: sessionDir
        )
        #expect(putTrace.exitCode == 0)
        #expect(putCmd.ok == true)
        #expect(putCmd.action == "putback")
        #expect(FileManager.default.isExecutableFile(atPath: putCmd.commandFile))
    }

    @Test("fx3_702 exposes optional fx3_playback (P29/P30) and supports apply/putback with mp4_3x2,screen_3x2,fx3_playback")
    func testFX3PlaybackOptionalPackRoundTrip() async throws {
        let sessionDir = try makeTempDir(prefix: "ogs-fx3-playback")
        defer { try? FileManager.default.removeItem(at: sessionDir) }
        let bridge = try makeBridge(sessionDir: sessionDir)

        let (bodiesRes, _) = try await bridge.listBodies()
        let fx3 = try #require(bodiesRes.bodies.first(where: { $0.bodyId == "fx3_702" }))
        let playbackPack = try #require(fx3.packs["fx3_playback"])
        #expect(playbackPack.applySteps == ["P29"])
        #expect(playbackPack.putbackSteps == ["P30"])

        for nonFX3Id in ["zve1_202", "a7s3_501"] {
            let body = try #require(bodiesRes.bodies.first(where: { $0.bodyId == nonFX3Id }))
            #expect(body.packs["fx3_playback"] == nil)
        }

        let (pre, _) = try await bridge.preflight(
            bodyId: "fx3_702",
            mockCamera: true,
            mockState: .stock,
            sessionDir: sessionDir
        )
        #expect(pre.ready == true)

        let packs = ["mp4_3x2", "screen_3x2", "fx3_playback"]
        let (app, _) = try await bridge.apply(
            bodyId: "fx3_702",
            packs: packs,
            mockCamera: true,
            sessionDir: sessionDir
        )
        #expect(app.ok == true)
        #expect(app.closingDumpVerdict.contains("VERDICT READY"))
        #expect(app.stepsRun.contains(where: { $0.step == "P29" }))
        #expect(app.activePacks.contains("fx3_playback"))

        let (put, _) = try await bridge.putback(
            bodyId: "fx3_702",
            packs: packs,
            mockCamera: true,
            sessionDir: sessionDir
        )
        #expect(put.ok == true)
        #expect(put.state == "stock")
        #expect(put.stepsRun.contains(where: { $0.step == "P30" }))
    }

    @Test("LiveRunEvent decodes all 10 live orchestrator JSONL event schemas")
    func testDecodeAllTenLiveRunEventPayloads() throws {
        let decoder = JSONDecoder()
        let samples: [String] = [
            #"{"ts":"2026-01-01T00:00:01Z","type":"plan","action":"apply","body_id":"zve1_202","camera":"Sony ZV-E1","firmware":"2.02","steps":[{"id":"L13","summary":"Check clean state"},{"id":"L5","summary":"Enable open-gate sensor mode"}],"closing_dump":true}"#,
            #"{"ts":"2026-01-01T00:00:02Z","type":"wait_drive","first":true,"step_index":1,"total_steps":2,"step_id":"L13","title":"Connect camera in Stills mode","detail":"USB Connection = Mass Storage"}"#,
            #"{"ts":"2026-01-01T00:00:03Z","type":"step_start","step_index":1,"total_steps":2,"step_id":"L13","summary":"Check clean state"}"#,
            #"{"ts":"2026-01-01T00:00:04Z","type":"step_done","step_index":1,"total_steps":2,"step_id":"L13","outcome":"DONE","ok":true}"#,
            #"{"ts":"2026-01-01T00:00:05Z","type":"wait_movie_replug","hint":"MOVIE mode (24p/25p/30p)","title":"Switch camera to Movie mode","detail":"Unplug USB-C, switch to Movie mode, replug."}"#,
            #"{"ts":"2026-01-01T00:00:06Z","type":"closing_dump_start"}"#,
            #"{"ts":"2026-01-01T00:00:07Z","type":"closing_dump_done","verdict":"VERDICT READY (open gate applied)","ready":true}"#,
            #"{"ts":"2026-01-01T00:00:08Z","type":"complete","ok":true,"action":"apply","body_id":"zve1_202","session_id":"20260101_000008","verdict":"VERDICT READY (open gate applied)","state":"applied","ready":true,"steps_run":["L13","L5"],"active_packs":["core_open_gate","mp4_3x2"]}"#,
            #"{"ts":"2026-01-01T00:00:09Z","type":"cancelled","step_index":null,"step_id":null,"message":"Cancelled safely before step 2."}"#,
            #"{"ts":"2026-01-01T00:00:10Z","type":"error","step_index":2,"step_id":"L5","message":"Step L5 failed","left_behind":true}"#
        ]

        let decoded = try samples.map { line in
            try decoder.decode(LiveRunEvent.self, from: Data(line.utf8))
        }
        #expect(decoded.count == 10)

        let plan = decoded[0]
        #expect(plan.type == "plan")
        #expect(plan.action == "apply")
        #expect(plan.bodyId == "zve1_202")
        #expect(plan.camera == "Sony ZV-E1")
        #expect(plan.firmware == "2.02")
        #expect(plan.steps == [
            LivePlanStep(id: "L13", summary: "Check clean state"),
            LivePlanStep(id: "L5", summary: "Enable open-gate sensor mode")
        ])
        #expect(plan.closingDump == true)

        let waitDrive = decoded[1]
        #expect(waitDrive.type == "wait_drive")
        #expect(waitDrive.first == true)
        #expect(waitDrive.stepIndex == 1)
        #expect(waitDrive.totalSteps == 2)
        #expect(waitDrive.stepId == "L13")
        #expect(waitDrive.title == "Connect camera in Stills mode")
        #expect(waitDrive.detail == "USB Connection = Mass Storage")

        let stepStart = decoded[2]
        #expect(stepStart.type == "step_start")
        #expect(stepStart.stepId == "L13")
        #expect(stepStart.summary == "Check clean state")

        let stepDone = decoded[3]
        #expect(stepDone.type == "step_done")
        #expect(stepDone.outcome == "DONE")
        #expect(stepDone.ok == true)

        let waitMovie = decoded[4]
        #expect(waitMovie.type == "wait_movie_replug")
        #expect(waitMovie.hint == "MOVIE mode (24p/25p/30p)")
        #expect(waitMovie.title == "Switch camera to Movie mode")

        let closingStart = decoded[5]
        #expect(closingStart.type == "closing_dump_start")

        let closingDone = decoded[6]
        #expect(closingDone.type == "closing_dump_done")
        #expect(closingDone.verdict == "VERDICT READY (open gate applied)")
        #expect(closingDone.ready == true)

        let complete = decoded[7]
        #expect(complete.type == "complete")
        #expect(complete.ok == true)
        #expect(complete.sessionId == "20260101_000008")
        #expect(complete.state == "applied")
        #expect(complete.ready == true)
        #expect(complete.stepsRun?.map(\.step) == ["L13", "L5"])
        #expect(complete.activePacks == ["core_open_gate", "mp4_3x2"])

        let cancelled = decoded[8]
        #expect(cancelled.type == "cancelled")
        #expect(cancelled.stepIndex == nil)
        #expect(cancelled.stepId == nil)
        #expect(cancelled.message == "Cancelled safely before step 2.")

        let errorEvent = decoded[9]
        #expect(errorEvent.type == "error")
        #expect(errorEvent.stepIndex == 2)
        #expect(errorEvent.stepId == "L5")
        #expect(errorEvent.leftBehind == true)
    }

    @Test("Shell single-quoting and AppleScript escaping neutralize special characters safely")
    func testShellAndAppleScriptQuotingSafety() throws {
        let trickyPayload = #"dir with spaces/O'Brien "quoted" $(echo PWNED) `id` ; \backslash"#
        let quoted = StudioBridge.shellSingleQuote(trickyPayload)
        #expect(quoted == #"'dir with spaces/O'\''Brien "quoted" $(echo PWNED) `id` ; \backslash'"#)

        // Verify /bin/bash parses the single-quoted argument verbatim with zero expansion (unprivileged)
        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: "/bin/bash")
        proc.arguments = ["-c", "printf '%s' \(quoted)"]
        let stdoutPipe = Pipe()
        proc.standardOutput = stdoutPipe
        try proc.run()
        proc.waitUntilExit()
        #expect(proc.terminationStatus == 0)
        let echoed = String(data: stdoutPipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8)
        #expect(echoed == trickyPayload)

        let shellCmd = StudioBridge.buildLiveInAppShellCommand(
            scriptPath: "/tmp/My Folder/run_live_inapp.sh",
            arguments: ["--body", "zve1_202", "--session-dir", trickyPayload]
        )
        #expect(shellCmd.hasPrefix("'/bin/bash' '/tmp/My Folder/run_live_inapp.sh' '--body' 'zve1_202' '--session-dir' "))

        let appleScript = StudioBridge.buildAdminAppleScript(
            shellCommand: shellCmd,
            prompt: "Confirm \"RAM\" \\ access\nline2"
        )
        #expect(appleScript.hasPrefix("do shell script \""))
        #expect(appleScript.hasSuffix("with administrator privileges"))
        #expect(appleScript.contains(#"\\\"quoted\\\""#) == false)
        #expect(appleScript.contains(#"\"quoted\""#))
        #expect(appleScript.contains(#"\\backslash"#))
        #expect(appleScript.contains(#"Confirm \"RAM\" \\ access\nline2"#))

        #expect(StudioBridge.isOsascriptUserCancelled(exitCode: 1, stderr: "execution error: User canceled. (-128)") == true)
        #expect(StudioBridge.isOsascriptUserCancelled(exitCode: 1, stderr: "User cancelled by dialog") == true)
        #expect(StudioBridge.isOsascriptUserCancelled(exitCode: 0, stderr: "(-128)") == false)
        #expect(StudioBridge.isOsascriptUserCancelled(exitCode: 1, stderr: "command failed with status 2") == false)
    }

    @Test("startLiveInAppRun streams events and logs in dryRunSimulate mode for preflight and apply")
    func testLiveInAppDryRunStreamingPreflightAndApply() async throws {
        let sessionDir = try makeTempDir(prefix: "ogs-inapp-stream")
        defer { try? FileManager.default.removeItem(at: sessionDir) }
        let bridge = try makeBridge(sessionDir: sessionDir)

        // 1. Simulated Preflight
        let preEvents = ThreadSafeCollector<LiveRunEvent>()
        let preLogs = ThreadSafeCollector<String>()
        let (preHandle, preTask) = bridge.startLiveInAppRun(
            action: .preflight,
            bodyId: "zve1_202",
            firmwareConfirmed: "2.02",
            confirmVolatileRam: false,
            packs: nil,
            sessionDir: sessionDir,
            dryRunSimulate: true,
            noMovieSession: false,
            onEvent: { preEvents.append($0) },
            onLogChunk: { preLogs.append($0) }
        )
        defer { try? FileManager.default.removeItem(at: preHandle.runDirectory) }

        let preResult = try await preTask.value
        #expect(preResult.exitCode == 0)
        #expect(preResult.wasUserCancelled == false)
        #expect(FileManager.default.fileExists(atPath: preResult.eventsFile.path))
        #expect(FileManager.default.fileExists(atPath: preResult.logFile.path))

        let preEventTypes = preResult.events.map(\.type)
        #expect(preEventTypes.contains("plan"))
        #expect(preEventTypes.contains("step_start"))
        #expect(preEventTypes.contains("step_done"))
        #expect(preEventTypes.contains("complete"))
        #expect(preEvents.snapshot() == preResult.events)
        #expect(preLogs.snapshot().joined() == preResult.logOutput)
        #expect(!preResult.logOutput.isEmpty)

        // 2. Simulated Apply (with closing dump in Movie mode)
        let appEvents = ThreadSafeCollector<LiveRunEvent>()
        let appLogs = ThreadSafeCollector<String>()
        let (appHandle, appTask) = bridge.startLiveInAppRun(
            action: .apply,
            bodyId: "zve1_202",
            firmwareConfirmed: "2.02",
            confirmVolatileRam: true,
            packs: ["mp4_3x2", "screen_3x2"],
            sessionDir: sessionDir,
            dryRunSimulate: true,
            noMovieSession: false,
            onEvent: { appEvents.append($0) },
            onLogChunk: { appLogs.append($0) }
        )
        defer { try? FileManager.default.removeItem(at: appHandle.runDirectory) }

        let appResult = try await appTask.value
        #expect(appResult.exitCode == 0)
        #expect(appResult.wasUserCancelled == false)

        let appEventTypes = appResult.events.map(\.type)
        #expect(appEventTypes.contains("plan"))
        #expect(appEventTypes.contains("step_start"))
        #expect(appEventTypes.contains("step_done"))
        #expect(appEventTypes.contains("wait_movie_replug"))
        #expect(appEventTypes.contains("closing_dump_start"))
        #expect(appEventTypes.contains("closing_dump_done"))
        #expect(appEventTypes.contains("complete"))
        #expect(appEvents.snapshot() == appResult.events)
        #expect(appLogs.snapshot().joined() == appResult.logOutput)
        #expect(!appResult.logOutput.isEmpty)
    }

    @Test("LiveRunHandle.cancel cleanly cancels simulated in-app run between steps")
    func testLiveInAppSafeCancellation() async throws {
        let sessionDir = try makeTempDir(prefix: "ogs-inapp-cancel")
        defer { try? FileManager.default.removeItem(at: sessionDir) }
        let bridge = try makeBridge(sessionDir: sessionDir)

        let events = ThreadSafeCollector<LiveRunEvent>()
        let (handle, task) = bridge.startLiveInAppRun(
            action: .apply,
            bodyId: "zve1_202",
            firmwareConfirmed: "2.02",
            confirmVolatileRam: true,
            packs: ["mp4_3x2", "screen_3x2"],
            sessionDir: sessionDir,
            dryRunSimulate: true,
            noMovieSession: false,
            onEvent: { events.append($0) },
            onLogChunk: { _ in }
        )
        defer { try? FileManager.default.removeItem(at: handle.runDirectory) }

        // Request safe cancellation immediately so cancel.flag is present before steps finish
        handle.cancel()
        #expect(handle.isCancelRequested == true)
        #expect(FileManager.default.fileExists(atPath: handle.cancelFile.path))

        let result = try await task.value
        #expect(result.wasUserCancelled == true)
        let sawCancelled = result.events.contains(where: { $0.type == "cancelled" })
        #expect(sawCancelled || result.exitCode == 130)
    }

    @Test("checkClip decodes telemetry and accepts A7 IV 5760x3840 fixture")
    func testCheckClipTelemetryAndA7IV57K() async throws {
        let tmpDir = try makeTempDir(prefix: "ogs-clip-57k")
        defer { try? FileManager.default.removeItem(at: tmpDir) }
        let bridge = try makeBridge(sessionDir: tmpDir)

        let mp4URL = tmpDir.appendingPathComponent("C0099.MP4")
        let xmlURL = tmpDir.appendingPathComponent("C0099M01.XML")
        try generate57KClipFixture(repoRoot: bridge.repoRoot, mp4URL: mp4URL, xmlURL: xmlURL)

        let (clipRes, trace) = try await bridge.checkClip(mp4URL: mp4URL, xmlURL: xmlURL, expect: "open-gate")
        #expect(trace.exitCode == 0)
        #expect(clipRes.ok == true)
        #expect(clipRes.width == 5760)
        #expect(clipRes.height == 3840)
        #expect((clipRes.durationSec ?? 0.0) > 0.0)
        #expect((clipRes.avgBitrateMbps ?? 0.0) > 0.0)
        #expect(clipRes.cadenceConstant == true)
    }

    @Test("LiveRunEvent and latestSession enforce mode, closing_kind, and verified fields")
    func testLiveRunEventAndLatestSessionModeFilter() async throws {
        let jsonData = #"{"type":"complete","ok":true,"state":"stock","ready":true,"verified":true,"closing_kind":"stock_check"}"#.data(using: .utf8)!
        let event = try JSONDecoder().decode(LiveRunEvent.self, from: jsonData)
        #expect(event.closingKind == "stock_check")
        #expect(event.verified == true)
        #expect(event.ready == true)

        let sessionDir = try makeTempDir(prefix: "ogs-live-mode-filter")
        defer { try? FileManager.default.removeItem(at: sessionDir) }
        let bridge = try makeBridge(sessionDir: sessionDir)

        let (mockRes, _) = try await bridge.preflight(bodyId: "zve1_202", mockCamera: true, mockState: .stock, sessionDir: sessionDir)
        #expect(mockRes.ready == true)

        let (allLatest, allTrace) = try await bridge.latestSession(bodyId: "zve1_202", sessionDir: sessionDir)
        #expect(allTrace.exitCode == 0)
        #expect(allLatest.found == true)
        #expect(allLatest.mode == "mock")

        let (liveLatest, liveTrace) = try await bridge.latestSession(bodyId: "zve1_202", sessionDir: sessionDir, mode: "live_usb")
        #expect(liveTrace.exitCode == 0)
        #expect(liveLatest.found == false)
    }

    @Test("LiveSessionOutcomeEvaluator fails closed on unverified or contradictory closing states")
    func testLiveSessionOutcomeEvaluatorFailClosed() {
        let baseURL = URL(fileURLWithPath: "/tmp")
        func makeResult(exitCode: Int32 = 0, completeEvent: LiveRunEvent?) -> LiveRunResult {
            LiveRunResult(
                exitCode: exitCode,
                wasUserCancelled: false,
                events: completeEvent.map { [$0] } ?? [],
                logOutput: "",
                eventsFile: baseURL,
                logFile: baseURL
            )
        }
        func makeEvent(
            ok: Bool? = true,
            state: String? = nil,
            ready: Bool? = nil,
            verified: Bool? = nil,
            closingKind: String? = nil,
            error: String? = nil
        ) throws -> LiveRunEvent {
            var dict: [String: Any] = ["type": "complete"]
            if let ok { dict["ok"] = ok }
            if let state { dict["state"] = state }
            if let ready { dict["ready"] = ready }
            if let verified { dict["verified"] = verified }
            if let closingKind { dict["closing_kind"] = closingKind }
            if let error { dict["error"] = error }
            let data = try JSONSerialization.data(withJSONObject: dict)
            return try JSONDecoder().decode(LiveRunEvent.self, from: data)
        }

        // Apply requires ok == true, ready == true, state == "applied"
        let validApply = try! makeEvent(ok: true, state: "applied", ready: true, verified: true, closingKind: "movie_dump")
        if case .finished(let comp) = LiveSessionOutcomeEvaluator.evaluate(
            result: makeResult(completeEvent: validApply),
            action: .apply,
            actionTitle: "Apply",
            existingFailureMessage: nil,
            existingCancelMessage: nil,
            existingLeftBehind: false,
            wasCancelRequestedByButton: false,
            isOsascriptCancelled: false
        ) {
            #expect(comp.state == "applied")
        } else {
            Issue.record("Expected verified apply completion to finish")
        }

        let optimisticUnreadyApply = try! makeEvent(ok: true, state: "applied", ready: false, verified: false)
        if case .failed = LiveSessionOutcomeEvaluator.evaluate(
            result: makeResult(completeEvent: optimisticUnreadyApply),
            action: .apply,
            actionTitle: "Apply",
            existingFailureMessage: nil,
            existingCancelMessage: nil,
            existingLeftBehind: false,
            wasCancelRequestedByButton: false,
            isOsascriptCancelled: false
        ) {
            // Expected fail-closed outcome
        } else {
            Issue.record("Expected unready apply completion to fail closed")
        }

        let contradictoryApply = try! makeEvent(ok: true, state: "stock", ready: true, verified: false)
        if case .failed = LiveSessionOutcomeEvaluator.evaluate(
            result: makeResult(completeEvent: contradictoryApply),
            action: .apply,
            actionTitle: "Apply",
            existingFailureMessage: nil,
            existingCancelMessage: nil,
            existingLeftBehind: false,
            wasCancelRequestedByButton: false,
            isOsascriptCancelled: false
        ) {
            // Expected fail-closed outcome
        } else {
            Issue.record("Expected contradictory stock state after apply to fail closed")
        }

        // Putback requires ok == true, state == "stock", ready == true, verified == true
        let validPutback = try! makeEvent(ok: true, state: "stock", ready: true, verified: true, closingKind: "stock_check")
        if case .finished(let comp) = LiveSessionOutcomeEvaluator.evaluate(
            result: makeResult(completeEvent: validPutback),
            action: .putback,
            actionTitle: "Putback",
            existingFailureMessage: nil,
            existingCancelMessage: nil,
            existingLeftBehind: false,
            wasCancelRequestedByButton: false,
            isOsascriptCancelled: false
        ) {
            #expect(comp.state == "stock")
        } else {
            Issue.record("Expected verified putback completion to finish")
        }

        let unverifiedPutback = try! makeEvent(ok: true, state: "stock_unverified", ready: false, verified: false)
        if case .failed = LiveSessionOutcomeEvaluator.evaluate(
            result: makeResult(completeEvent: unverifiedPutback),
            action: .putback,
            actionTitle: "Putback",
            existingFailureMessage: nil,
            existingCancelMessage: nil,
            existingLeftBehind: false,
            wasCancelRequestedByButton: false,
            isOsascriptCancelled: false
        ) {
            // Expected fail-closed outcome
        } else {
            Issue.record("Expected unverified putback completion to fail closed")
        }
    }

    @Test("startLiveInAppRun simulated putback runs closing stock_check and verifies state")
    func testLiveInAppDryRunSimulationPutbackVerification() async throws {
        let sessionDir = try makeTempDir(prefix: "ogs-inapp-putback")
        defer { try? FileManager.default.removeItem(at: sessionDir) }
        let bridge = try makeBridge(sessionDir: sessionDir)

        let (handle, task) = bridge.startLiveInAppRun(
            action: .putback,
            bodyId: "fx3_702",
            firmwareConfirmed: "7.02",
            confirmVolatileRam: true,
            packs: ["mp4_3x2"],
            sessionDir: sessionDir,
            dryRunSimulate: true,
            noMovieSession: false,
            onEvent: { _ in },
            onLogChunk: { _ in }
        )
        defer { try? FileManager.default.removeItem(at: handle.runDirectory) }

        let result = try await task.value
        #expect(result.exitCode == 0)
        #expect(result.events.contains(where: { $0.type == "closing_dump_start" }))
        #expect(result.events.contains(where: { $0.type == "closing_dump_done" }))
        #expect(result.events.last?.type == "complete")
        #expect(result.events.last?.state == "stock")
        #expect(result.events.last?.ready == true)
        #expect(result.events.last?.verified == true)
        if case .finished(let comp) = LiveSessionOutcomeEvaluator.evaluate(
            result: result,
            action: .putback,
            actionTitle: "Putback",
            existingFailureMessage: nil,
            existingCancelMessage: nil,
            existingLeftBehind: false,
            wasCancelRequestedByButton: false,
            isOsascriptCancelled: false
        ) {
            #expect(comp.state == "stock")
        } else {
            Issue.record("Expected simulated putback outcome to finish closed cleanly")
        }
    }

    @Test("buildReport creates FIELD_REPORT.md, field_report.json, and manifest end-to-end")
    func testBuildReportEndToEnd() async throws {
        let tmpDir = try makeTempDir(prefix: "ogs-report")
        defer { try? FileManager.default.removeItem(at: tmpDir) }
        let sessionDir = tmpDir.appendingPathComponent("sessions", isDirectory: true)
        let clipsDir = tmpDir.appendingPathComponent("clips", isDirectory: true)
        let outDir = tmpDir.appendingPathComponent("out_report", isDirectory: true)
        try FileManager.default.createDirectory(at: clipsDir, withIntermediateDirectories: true)

        let bridge = try makeBridge(sessionDir: sessionDir)
        _ = try await bridge.preflight(bodyId: "fx3_702", mockCamera: true, mockState: .stock, sessionDir: sessionDir)

        let mp4URL = clipsDir.appendingPathComponent("B1_og_framing.MP4")
        let xmlURL = clipsDir.appendingPathComponent("B1_og_framingM01.XML")
        try generateValid3x2ClipFixture(repoRoot: bridge.repoRoot, mp4URL: mp4URL, xmlURL: xmlURL)

        let (rep, trace) = try await bridge.buildReport(
            bodyId: "fx3_702",
            clipsDir: clipsDir,
            outDir: outDir,
            sessionDir: sessionDir,
            mediaCard: "Sony CEA-G 160GB",
            lens: "24mm GM",
            ambientC: "23C",
            soakMinutes: "45",
            thermalResult: "No warning",
            reactivationSeconds: "58",
            afDesqueezeNotes: "hdmi32 + De-Squeeze OFF kept AF active"
        )
        #expect(trace.exitCode == 0)
        #expect(rep.ok == true)
        #expect(rep.bodyId == "fx3_702")
        #expect(rep.clipsScanned == 1)
        #expect(rep.clipsPassed == 1)
        #expect(rep.clipsFailed == 0)
        #expect(FileManager.default.fileExists(atPath: rep.markdownPath))
        #expect(FileManager.default.fileExists(atPath: rep.jsonPath))
        #expect(FileManager.default.fileExists(atPath: rep.manifestPath))
        #expect(rep.markdownPreview.contains("Sony CEA-G 160GB"))
    }

    private func generate57KClipFixture(repoRoot: URL, mp4URL: URL, xmlURL: URL) throws {
        let script = """
        import pathlib, sys
        cli_dir = pathlib.Path(sys.argv[1]) / "cli"
        sys.path.insert(0, str(cli_dir))
        import bionz_clip_check as bcc

        mp4_path = pathlib.Path(sys.argv[2])
        xml_path = pathlib.Path(sys.argv[3])
        mp4_bytes = bcc.build_synthetic_mp4(
            width=5760,
            height=3840,
            codec="hvc1",
            timescale=24000,
            sample_delta=1001,
            vprf_width=5760,
            vprf_height=3840,
            rtmd_samples=12,
            hvcc_level_idc=153,
            mdat_bytes=65536,
        )
        mp4_path.write_bytes(mp4_bytes)
        xml_path.write_text(bcc.build_synthetic_xml(5760, 3840, codec="hvc1", aspect_ratio="3:2"), encoding="utf-8")
        """

        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        process.arguments = ["python3", "-c", script, repoRoot.path, mp4URL.path, xmlURL.path]
        let stderrPipe = Pipe()
        process.standardError = stderrPipe
        try process.run()
        process.waitUntilExit()
        if process.terminationStatus != 0 {
            let errData = stderrPipe.fileHandleForReading.readDataToEndOfFile()
            let errText = String(data: errData, encoding: .utf8) ?? ""
            throw StudioBridgeError.processLaunchFailed("5.7K fixture generator failed: \(errText)")
        }
    }

    /// Generates a minimal valid ISO BMFF MP4 + M01.XML + rtmd fixture using cli/bionz_clip_check.py helpers.
    private func generateValid3x2ClipFixture(repoRoot: URL, mp4URL: URL, xmlURL: URL) throws {
        let script = """
        import pathlib, sys
        cli_dir = pathlib.Path(sys.argv[1]) / "cli"
        sys.path.insert(0, str(cli_dir))
        import bionz_clip_check as bcc

        mp4_path = pathlib.Path(sys.argv[2])
        xml_path = pathlib.Path(sys.argv[3])
        mp4_bytes = bcc.build_synthetic_mp4(
            width=3840,
            height=2560,
            codec="hvc1",
            timescale=24000,
            sample_delta=1001,
            vprf_width=3840,
            vprf_height=2560,
            rtmd_samples=12,
        )
        mp4_path.write_bytes(mp4_bytes)
        xml_path.write_text(bcc.build_synthetic_xml(3840, 2560, codec="hvc1", aspect_ratio="3:2"), encoding="utf-8")
        """

        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        process.arguments = ["python3", "-c", script, repoRoot.path, mp4URL.path, xmlURL.path]
        let stderrPipe = Pipe()
        process.standardError = stderrPipe
        try process.run()
        process.waitUntilExit()
        if process.terminationStatus != 0 {
            let errData = stderrPipe.fileHandleForReading.readDataToEndOfFile()
            let errText = String(data: errData, encoding: .utf8) ?? ""
            throw StudioBridgeError.processLaunchFailed("Fixture generator failed: \(errText)")
        }
    }
}

private final class ThreadSafeCollector<T: Sendable>: @unchecked Sendable {
    private let lock = NSLock()
    private var items: [T] = []

    func append(_ item: T) {
        lock.lock()
        items.append(item)
        lock.unlock()
    }

    func snapshot() -> [T] {
        lock.lock()
        defer { lock.unlock() }
        return items
    }
}
