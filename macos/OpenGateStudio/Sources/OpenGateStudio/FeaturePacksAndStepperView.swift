import OpenGateStudioCore
import SwiftUI

private struct PackMetadata {
    let id: String
    let title: String
    let subtitle: String
    let icon: String
    let defaultStepsHint: String
}

public struct FeaturePacksAndStepperView: View {
    @EnvironmentObject private var appState: AppState

    private let modularCatalog: [PackMetadata] = [
        PackMetadata(
            id: "mp4_3x2",
            title: "MP4 3:2 Native Container + Playback",
            subtitle: "Writes native 3840x2560 MP4 dimensions & preserves Sony rtmd gyro track (23.98p hardware core; 25p/29.97p & NLE/Gyroflow corpus qualification ongoing).",
            icon: "film.stack",
            defaultStepsHint: "V19 / V20 (fallback L19 / L20)"
        ),
        PackMetadata(
            id: "screen_3x2",
            title: "3:2 LCD / EVF Desqueeze + C2 Cycle",
            subtitle: "Enables uncropped 3:2 viewfinder framing with C2/C3 live aspect cycle (ZV-E1/a7S III) or native De-Squeeze (FX3).",
            icon: "rectangle.aspectratio",
            defaultStepsHint: "S16 + C19 / C20 + S17"
        ),
        PackMetadata(
            id: "hdmi32",
            title: "HDMI 3:2 Output",
            subtitle: "Experimental: outputs clean 3:2 open-gate feed over HDMI to external monitors/recorders (emulator-verified; awaiting hardware corpus).",
            icon: "display",
            defaultStepsHint: "H16 / H17"
        ),
        PackMetadata(
            id: "high_bitrate",
            title: "High-Bitrate Long-GOP (200M / 300M)",
            subtitle: "Experimental: unlocks 200 Mbps / 300 Mbps Long-GOP overlays for XAVC HS & XAVC S (emulator-verified; awaiting sustained soak clips).",
            icon: "speedometer",
            defaultStepsHint: "B19 / B20"
        ),
        PackMetadata(
            id: "xavc_si",
            title: "XAVC S-I 3840x2560 All-Intra",
            subtitle: "Experimental: enables 3:2 open-gate recording in XAVC S-I intra-frame mode (23.98p / 25p / 29.97p; emulator-verified).",
            icon: "waveform.path.ecg.rectangle",
            defaultStepsHint: "I19 / I20"
        ),
        PackMetadata(
            id: "fx3_playback",
            title: "FX3 Open-Gate Playback Fix",
            subtitle: "Experimental FX3 playback path patch for 3:2 open-gate clips (P29 / P30 — untested on hardware).",
            icon: "play.rectangle.on.rectangle",
            defaultStepsHint: "P29 / P30"
        )
    ]

    public init() {}

    public var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                HStack(alignment: .top, spacing: 18) {
                    packsColumn
                        .frame(minWidth: 360, maxWidth: 430)

                    stepperColumn
                        .frame(maxWidth: .infinity)
                }

                consolePane
            }
            .padding(18)
        }
    }

    // MARK: - Feature Packs Column

    private var packsColumn: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("Feature Packs")
                    .font(.title3.weight(.semibold))
                Spacer()
                if let bodyInfo = appState.selectedBody {
                    Text(bodyInfo.displayName)
                        .font(.caption.weight(.medium))
                        .padding(.horizontal, 8)
                        .padding(.vertical, 3)
                        .background(Color.secondary.opacity(0.14))
                        .clipShape(Capsule())
                }
            }

            HStack(spacing: 8) {
                Text("Presets:")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                Button("Safe Daily 3:2 (Recommended)") {
                    appState.applyPackPreset(.safeDaily)
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.mini)
                Button("Cinema + All-Intra + HDMI (Experimental)") {
                    appState.applyPackPreset(.cinemaFull)
                }
                .buttonStyle(.bordered)
                .controlSize(.mini)
            }

            requiredCoreCard

            ForEach(modularCatalog, id: \.id) { meta in
                if meta.id != "fx3_playback" || appState.selectedBody?.packs[meta.id] != nil {
                    modularPackCard(meta)
                }
            }
        }
    }

    private var requiredCoreCard: some View {
        let corePack = appState.selectedBody?.packs["core_open_gate"]
        let stepsText = corePack?.applySteps.joined(separator: " -> ") ?? "L13 -> L5 -> L16"

        return HStack(alignment: .top, spacing: 12) {
            Image(systemName: "lock.fill")
                .font(.title3)
                .foregroundStyle(.blue)
                .frame(width: 28, height: 28)

            VStack(alignment: .leading, spacing: 4) {
                HStack {
                    Text("core_open_gate")
                        .font(.headline)
                    Spacer()
                    Text("REQUIRED")
                        .font(.caption2.weight(.bold))
                        .padding(.horizontal, 8)
                        .padding(.vertical, 3)
                        .background(Color.blue.opacity(0.16))
                        .foregroundStyle(.blue)
                        .clipShape(Capsule())
                }
                Text(corePack?.summary ?? corePack?.description ?? "3840x2560 Open-Gate readout & base encoder enablement in volatile RAM.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Text("Steps: \(stepsText)")
                    .font(.caption2.monospaced())
                    .foregroundStyle(.secondary)
            }
        }
        .padding(12)
        .background(
            RoundedRectangle(cornerRadius: 10)
                .fill(Color.blue.opacity(0.06))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 10)
                .stroke(Color.blue.opacity(0.30), lineWidth: 1)
        )
    }

    private func displayTitle(for meta: PackMetadata) -> String {
        guard meta.id == "screen_3x2" else { return meta.title }
        switch appState.selectedBodyId {
        case "fx3_702":
            return "3:2 Rear LCD & Native De-Squeeze"
        case "a7s3_501":
            return "3:2 LCD / EVF & C3 Cycle"
        default:
            return "3:2 LCD Fill & C2 Cycle"
        }
    }

    private func modularPackCard(_ meta: PackMetadata) -> some View {
        let manifestPack = appState.selectedBody?.packs[meta.id]
        let isAvailable = appState.selectedBody == nil || manifestPack != nil
        let isEnabled = appState.isPackEnabled(meta.id)
        let stepsDisplay = manifestPack.map { pack in
            let apply = pack.applySteps.joined(separator: ", ")
            let putback = pack.putbackSteps.joined(separator: ", ")
            return "Apply: [\(apply)]  •  Putback: [\(putback)]"
        } ?? meta.defaultStepsHint

        let isExperimentalFX3Playback = meta.id == "fx3_playback"
        let isExperimentalPack = meta.id == "hdmi32" || meta.id == "high_bitrate" || meta.id == "xavc_si"
        let isRecommendedPack = meta.id == "mp4_3x2" || meta.id == "screen_3x2"
        let showHdmiAfTip = meta.id == "hdmi32" && (isEnabled || appState.selectedBodyId == "fx3_702")

        return HStack(alignment: .top, spacing: 12) {
            Image(systemName: meta.icon)
                .font(.title3)
                .foregroundStyle(isEnabled ? Color.accentColor : Color.secondary)
                .frame(width: 28, height: 28)

            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 6) {
                    Text(displayTitle(for: meta))
                        .font(.subheadline.weight(.semibold))
                    if isExperimentalFX3Playback {
                        Text("UNTESTED ON HARDWARE")
                            .font(.caption2.weight(.bold))
                            .padding(.horizontal, 6)
                            .padding(.vertical, 2)
                            .background(Color.orange.opacity(0.18))
                            .foregroundStyle(.orange)
                            .clipShape(Capsule())
                    } else if isExperimentalPack {
                        Text("EXPERIMENTAL")
                            .font(.caption2.weight(.bold))
                            .padding(.horizontal, 6)
                            .padding(.vertical, 2)
                            .background(Color.orange.opacity(0.18))
                            .foregroundStyle(.orange)
                            .clipShape(Capsule())
                    } else if isRecommendedPack {
                        Text("RECOMMENDED")
                            .font(.caption2.weight(.bold))
                            .padding(.horizontal, 6)
                            .padding(.vertical, 2)
                            .background(Color.green.opacity(0.16))
                            .foregroundStyle(.green)
                            .clipShape(Capsule())
                    }
                    Spacer()
                    Toggle(
                        meta.id,
                        isOn: Binding(
                            get: { isEnabled },
                            set: { appState.setPack(meta.id, enabled: $0) }
                        )
                    )
                    .labelsHidden()
                    .toggleStyle(.switch)
                    .controlSize(.small)
                    .disabled(!isAvailable)
                }

                Text(manifestPack?.summary ?? manifestPack?.description ?? meta.subtitle)
                    .font(.caption)
                    .foregroundStyle(.secondary)

                if showHdmiAfTip {
                    HStack(alignment: .top, spacing: 6) {
                        Image(systemName: "info.circle.fill")
                            .font(.caption)
                            .foregroundStyle(.blue)
                        Text("AF + Anamorphic Tip: Leave FX3 internal De-Squeeze OFF to keep Sony AF active and de-squeeze clean 3:2 on your external HDMI monitor.")
                            .font(.caption2.weight(.medium))
                            .foregroundStyle(.blue)
                    }
                    .padding(6)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Color.blue.opacity(0.08))
                    .clipShape(RoundedRectangle(cornerRadius: 6))
                }

                if isExperimentalFX3Playback {
                    HStack(alignment: .top, spacing: 6) {
                        Image(systemName: "exclamationmark.triangle.fill")
                            .font(.caption)
                            .foregroundStyle(.orange)
                        Text("Test 1 normal 16:9 clip first; if open-gate clip says Unable to Display, do NOT retry")
                            .font(.caption2.weight(.medium))
                            .foregroundStyle(.orange)
                    }
                    .padding(6)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Color.orange.opacity(0.10))
                    .clipShape(RoundedRectangle(cornerRadius: 6))
                }

                HStack(spacing: 6) {
                    Text(meta.id)
                        .font(.caption2.monospaced())
                        .padding(.horizontal, 6)
                        .padding(.vertical, 2)
                        .background(Color.secondary.opacity(0.12))
                        .clipShape(RoundedRectangle(cornerRadius: 4))
                    Text(stepsDisplay)
                        .font(.caption2.monospaced())
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
            }
        }
        .padding(12)
        .background(
            RoundedRectangle(cornerRadius: 10)
                .fill(Color(nsColor: .controlBackgroundColor))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 10)
                .stroke(isEnabled ? Color.accentColor.opacity(0.45) : Color.secondary.opacity(0.18), lineWidth: 1)
        )
        .opacity(isAvailable ? 1.0 : 0.55)
    }

    // MARK: - 5-Gate Safety Stepper Column

    private var stepperColumn: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Text("5-Gate Volatile RAM Safety Stepper")
                    .font(.title3.weight(.semibold))
                Spacer()
                Text("Battery Pull Restores Stock")
                    .font(.caption.weight(.medium))
                    .foregroundStyle(.secondary)
            }

            if !appState.offlineMockCamera {
                liveUsbModeBanner
            }

            if let err = appState.stepperError {
                HStack(spacing: 8) {
                    Image(systemName: "xmark.octagon.fill")
                        .foregroundStyle(.red)
                    Text(err)
                        .font(.callout)
                    Spacer()
                }
                .padding(10)
                .background(Color.red.opacity(0.12))
                .clipShape(RoundedRectangle(cornerRadius: 8))
            }

            // Gate 1: Cold-Boot Stills Checklist
            gateCard(
                number: 1,
                title: "Cold-Boot Stills Checklist",
                statusColor: appState.isChecklistComplete ? .green : .orange,
                statusText: appState.isChecklistComplete ? "Confirmed" : "Action Required"
            ) {
                VStack(alignment: .leading, spacing: 8) {
                    Toggle(
                        "Battery was physically pulled for >= 10 seconds (cold RAM baseline)",
                        isOn: $appState.batteryPulled10s
                    )
                    Toggle(
                        "Camera dial is in Stills mode before USB connection",
                        isOn: $appState.cameraInStillsMode
                    )

                    HStack {
                        Button {
                            appState.selectedTab = .setupGuide
                        } label: {
                            Label("Open Camera Setup Checklist", systemImage: "checklist")
                        }
                        .buttonStyle(.link)
                        .font(.caption)
                        Spacer()
                    }
                }
                .font(.callout)
            }

            // Gate 2: Read-Only Preflight
            gateCard(
                number: 2,
                title: "Read-Only Preflight Verification",
                statusColor: preflightStatusColor,
                statusText: preflightStatusText
            ) {
                VStack(alignment: .leading, spacing: 10) {
                    HStack {
                        Button {
                            Task { await appState.runPreflight() }
                        } label: {
                            HStack(spacing: 6) {
                                if appState.isRunningPreflight {
                                    ProgressView().controlSize(.small)
                                } else {
                                    Image(systemName: "magnifyingglass.circle.fill")
                                }
                                Text("Run Read-Only Preflight")
                            }
                        }
                        .buttonStyle(.borderedProminent)
                        .disabled(!appState.isChecklistComplete || appState.isRunningPreflight || appState.isLiveSessionActive)

                        if !appState.offlineMockCamera {
                            Button {
                                Task { await appState.syncLatestCameraSession() }
                            } label: {
                                HStack(spacing: 5) {
                                    if appState.isSyncingSession {
                                        ProgressView().controlSize(.small)
                                    } else {
                                        Image(systemName: "arrow.triangle.2.circlepath")
                                    }
                                    Text("Sync Latest Camera Session")
                                }
                            }
                            .buttonStyle(.bordered)
                            .disabled(appState.isSyncingSession)
                        }

                        if !appState.isChecklistComplete {
                            Text("Complete Gate 1 checklist first")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }

                    if let preflight = appState.preflightResult {
                        VStack(alignment: .leading, spacing: 6) {
                            HStack(spacing: 8) {
                                Image(systemName: preflight.ready ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                                    .foregroundStyle(preflight.ready ? .green : .red)
                                Text(preflight.verdict)
                                    .font(.callout.weight(.semibold))
                                Spacer()
                                resultSourceBadge
                            }
                            Text("State: \(preflight.state)  •  Session: \(preflight.sessionId)")
                                .font(.caption.monospaced())
                                .foregroundStyle(.secondary)
                        }
                        .padding(10)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(preflight.ready ? Color.green.opacity(0.10) : Color.red.opacity(0.10))
                        .clipShape(RoundedRectangle(cornerRadius: 8))
                    }

                    if appState.isMixedPowerSwitchWarning {
                        HStack(alignment: .top, spacing: 8) {
                            Image(systemName: "battery.0")
                                .font(.title3)
                                .foregroundStyle(.red)
                            VStack(alignment: .leading, spacing: 2) {
                                Text("Warm Power-Switch Mixed State Detected")
                                    .font(.callout.weight(.bold))
                                    .foregroundStyle(.red)
                                Text("Pull battery for at least 10 seconds to clear residual RAM state before re-running preflight. Apply remains locked.")
                                    .font(.caption)
                            }
                        }
                        .padding(10)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(Color.red.opacity(0.14))
                        .overlay(
                            RoundedRectangle(cornerRadius: 8)
                                .stroke(Color.red.opacity(0.45), lineWidth: 1)
                        )
                        .clipShape(RoundedRectangle(cornerRadius: 8))
                    }
                }
            }

            // Gate 3: Apply Selected Packs
            gateCard(
                number: 3,
                title: "Apply Selected Packs to Volatile RAM",
                statusColor: appState.applyResult != nil ? .green : (appState.isApplyUnlocked ? .blue : .secondary),
                statusText: appState.applyResult != nil ? "Applied" : (appState.isApplyUnlocked ? "Unlocked" : "Locked")
            ) {
                VStack(alignment: .leading, spacing: 10) {
                    HStack {
                        Button {
                            Task { await appState.applySelectedPacks() }
                        } label: {
                            HStack(spacing: 6) {
                                if appState.isApplying {
                                    ProgressView().controlSize(.small)
                                } else {
                                    Image(systemName: "bolt.shield.fill")
                                }
                                Text("Apply Selected Packs")
                            }
                        }
                        .buttonStyle(.borderedProminent)
                        .tint(.green)
                        .disabled(!appState.isApplyUnlocked || appState.isApplying || appState.isLiveSessionActive)

                        if !appState.isApplyUnlocked {
                            Text(
                                appState.offlineMockCamera
                                    ? "Requires Gate 2 preflight ready == true"
                                    : "Requires Gate 1 + Live Read-Only Preflight (VERDICT READY)"
                            )
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }

                    if let apply = appState.applyResult {
                        VStack(alignment: .leading, spacing: 8) {
                            HStack {
                                Text("Ordered .so Steps Executed:")
                                    .font(.caption.weight(.semibold))
                                    .foregroundStyle(.secondary)
                                Spacer()
                                resultSourceBadge
                            }

                            ScrollView(.horizontal, showsIndicators: false) {
                                HStack(spacing: 6) {
                                    ForEach(Array(apply.stepsRun.enumerated()), id: \.offset) { idx, item in
                                        HStack(spacing: 4) {
                                            Text("\(idx + 1). \(item.step)")
                                                .font(.caption.monospaced().weight(.semibold))
                                            if let status = item.status {
                                                Text("(\(status))")
                                                    .font(.caption2.monospaced())
                                                    .foregroundStyle(.secondary)
                                            }
                                        }
                                        .padding(.horizontal, 8)
                                        .padding(.vertical, 4)
                                        .background(Color.green.opacity(0.14))
                                        .clipShape(RoundedRectangle(cornerRadius: 6))
                                    }
                                }
                            }

                            HStack(spacing: 8) {
                                Image(systemName: "checkmark.seal.fill")
                                    .foregroundStyle(.green)
                                Text("Step 6 Closing Movie Dump: \(apply.closingDumpVerdict)")
                                    .font(.callout.weight(.semibold))
                            }

                            if !apply.activePacks.isEmpty {
                                Text("Active Packs: \(apply.activePacks.joined(separator: ", "))")
                                    .font(.caption.monospaced())
                                    .foregroundStyle(.secondary)
                            }
                        }
                        .padding(10)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(Color.green.opacity(0.08))
                        .clipShape(RoundedRectangle(cornerRadius: 8))
                    }
                }
            }

            // Gate 4: Put Back to Stock
            let putbackVerified = appState.putbackResult.map { $0.ok && $0.state == "stock" } ?? false
            gateCard(
                number: 4,
                title: "Put Back to Stock RAM",
                statusColor: appState.putbackResult == nil ? .secondary : (putbackVerified ? .green : .red),
                statusText: appState.putbackResult == nil ? "Standby" : (putbackVerified ? "Verified Stock" : "Unverified")
            ) {
                VStack(alignment: .leading, spacing: 10) {
                    Button {
                        Task { await appState.putBackToStock() }
                    } label: {
                        HStack(spacing: 6) {
                            if appState.isPuttingBack {
                                ProgressView().controlSize(.small)
                            } else {
                                Image(systemName: "arrow.uturn.backward.circle.fill")
                            }
                            Text("Put Back to Stock")
                        }
                    }
                    .buttonStyle(.bordered)
                    .disabled(appState.isPuttingBack || appState.isLiveSessionActive)

                    if let putback = appState.putbackResult {
                        let isOk = putback.ok && putback.state == "stock"
                        VStack(alignment: .leading, spacing: 4) {
                            HStack {
                                Text("State: \(putback.state)  •  Steps: \(putback.stepsRun.map(\.step).joined(separator: " -> "))")
                                    .font(.caption.monospaced())
                                Spacer()
                                resultSourceBadge
                            }
                        }
                        .padding(8)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background((isOk ? Color.blue : Color.red).opacity(0.08))
                        .clipShape(RoundedRectangle(cornerRadius: 8))
                    }
                }
            }
        }
    }

    // MARK: - Gate 5: Expandable Console Log Pane

    private var consolePane: some View {
        DisclosureGroup(isExpanded: $appState.isConsoleExpanded) {
            VStack(alignment: .leading, spacing: 8) {
                if appState.consoleLogs.isEmpty {
                    Text("No CLI invocations recorded yet.")
                        .font(.caption.monospaced())
                        .foregroundStyle(.secondary)
                        .padding(.vertical, 8)
                } else {
                    ForEach(appState.consoleLogs) { trace in
                        VStack(alignment: .leading, spacing: 4) {
                            HStack {
                                Text("$ \(trace.command)")
                                    .font(.caption.monospaced().weight(.semibold))
                                    .textSelection(.enabled)
                                Spacer()
                                Text("exit \(trace.exitCode)")
                                    .font(.caption2.monospaced())
                                    .padding(.horizontal, 6)
                                    .padding(.vertical, 2)
                                    .background(trace.exitCode == 0 ? Color.green.opacity(0.18) : Color.red.opacity(0.18))
                                    .clipShape(Capsule())
                            }
                            if !trace.stdout.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                                Text(trace.stdout.trimmingCharacters(in: .whitespacesAndNewlines))
                                    .font(.caption2.monospaced())
                                    .foregroundStyle(.secondary)
                                    .textSelection(.enabled)
                            }
                            if !trace.stderr.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                                Text("stderr: \(trace.stderr.trimmingCharacters(in: .whitespacesAndNewlines))")
                                    .font(.caption2.monospaced())
                                    .foregroundStyle(.red)
                                    .textSelection(.enabled)
                            }
                        }
                        .padding(8)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(Color(nsColor: .textBackgroundColor))
                        .clipShape(RoundedRectangle(cornerRadius: 6))
                    }
                }
            }
            .padding(.top, 8)
        } label: {
            HStack {
                Label("Gate 5: Console Log (\(appState.consoleLogs.count))", systemImage: "terminal")
                    .font(.headline)
                Spacer()
                if !appState.consoleLogs.isEmpty {
                    Button("Clear") {
                        appState.consoleLogs.removeAll()
                    }
                    .buttonStyle(.borderless)
                    .font(.caption)
                }
            }
        }
        .padding(12)
        .background(
            RoundedRectangle(cornerRadius: 10)
                .fill(Color(nsColor: .controlBackgroundColor))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 10)
                .stroke(Color.secondary.opacity(0.18), lineWidth: 1)
        )
    }

    private var liveUsbModeBanner: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .top, spacing: 10) {
                Image(systemName: "cable.connector")
                    .font(.title3)
                    .foregroundStyle(.blue)
                    .frame(width: 24, height: 24)

                VStack(alignment: .leading, spacing: 4) {
                    HStack {
                        Text("Live Camera USB Mode — Native In-App")
                            .font(.subheadline.weight(.semibold))
                        Spacer()
                        Button {
                            Task { await appState.syncLatestCameraSession() }
                        } label: {
                            HStack(spacing: 5) {
                                if appState.isSyncingSession {
                                    ProgressView().controlSize(.small)
                                } else {
                                    Image(systemName: "arrow.triangle.2.circlepath")
                                }
                                Text("Sync Latest Session")
                            }
                        }
                        .buttonStyle(.bordered)
                        .controlSize(.small)
                        .disabled(appState.isSyncingSession || appState.isLiveSessionActive)
                    }

                    Text("Runs natively in OpenGate Studio with macOS administrator approval — no Terminal required. You'll confirm your firmware with clickable switches, follow visual USB replug banners, and sync results automatically.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }

            if appState.liveStatusBanner != nil || appState.preparedLiveCommandPath != nil {
                VStack(alignment: .leading, spacing: 6) {
                    if let status = appState.liveStatusBanner {
                        Text(status)
                            .font(.caption.weight(.medium))
                    }
                    if let cmdPath = appState.preparedLiveCommandPath {
                        HStack(spacing: 8) {
                            Text(cmdPath)
                                .font(.caption2.monospaced())
                                .foregroundStyle(.secondary)
                                .textSelection(.enabled)
                                .lineLimit(2)
                            Spacer()
                            Button("Open Terminal Fallback") {
                                appState.openPreparedLiveCommand()
                            }
                            .buttonStyle(.bordered)
                            .controlSize(.mini)
                        }
                    }
                    if let preview = appState.preparedLiveCommandPreview, !preview.isEmpty {
                        Text(preview)
                            .font(.caption2.monospaced())
                            .foregroundStyle(.secondary)
                            .textSelection(.enabled)
                    }
                }
                .padding(8)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(Color(nsColor: .textBackgroundColor).opacity(0.7))
                .clipShape(RoundedRectangle(cornerRadius: 6))
            }
        }
        .padding(12)
        .background(
            RoundedRectangle(cornerRadius: 10)
                .fill(Color.blue.opacity(0.07))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 10)
                .stroke(Color.blue.opacity(0.30), lineWidth: 1)
        )
    }

    @ViewBuilder
    private var resultSourceBadge: some View {
        let source = appState.lastResultSource ?? (appState.offlineMockCamera ? .mock : .liveInApp)
        let badgeColor: Color = {
            switch source {
            case .mock: return .blue
            case .liveInApp: return .green
            case .liveTerminal: return .orange
            }
        }()
        Text(source.rawValue)
            .font(.caption2.weight(.semibold))
            .padding(.horizontal, 7)
            .padding(.vertical, 2)
            .background(badgeColor.opacity(0.16))
            .foregroundStyle(badgeColor)
            .clipShape(Capsule())
    }

    private var preflightStatusColor: Color {
        guard let preflight = appState.preflightResult else { return .secondary }
        return preflight.ready ? .green : .red
    }

    private var preflightStatusText: String {
        guard let preflight = appState.preflightResult else { return "Pending" }
        return preflight.ready ? "Ready (\(preflight.state))" : "Blocked (\(preflight.state))"
    }

    private func gateCard<Content: View>(
        number: Int,
        title: String,
        statusColor: Color,
        statusText: String,
        @ViewBuilder content: () -> Content
    ) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text("Gate \(number)")
                    .font(.caption.weight(.bold))
                    .padding(.horizontal, 8)
                    .padding(.vertical, 3)
                    .background(statusColor.opacity(0.16))
                    .foregroundStyle(statusColor)
                    .clipShape(Capsule())

                Text(title)
                    .font(.headline)

                Spacer()

                Text(statusText)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(statusColor)
            }

            content()
        }
        .padding(14)
        .background(
            RoundedRectangle(cornerRadius: 10)
                .fill(Color(nsColor: .controlBackgroundColor))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 10)
                .stroke(statusColor.opacity(0.28), lineWidth: 1)
        )
    }
}
