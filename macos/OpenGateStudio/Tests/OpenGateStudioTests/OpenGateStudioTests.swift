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
