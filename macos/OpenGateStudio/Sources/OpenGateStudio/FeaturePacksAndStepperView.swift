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
            subtitle: "Writes native 3840x2560 MP4 dimensions & playback scaling; suppresses 16:9 NRT XML aspect.",
            icon: "film.stack",
            defaultStepsHint: "V19 / V20 (fallback L19 / L20)"
        ),
        PackMetadata(
            id: "screen_3x2",
            title: "3:2 LCD / EVF Desqueeze + C2 Cycle",
            subtitle: "Enables uncropped 3:2 viewfinder framing with C2 live aspect cycle.",
            icon: "rectangle.aspectratio",
            defaultStepsHint: "S16 + C19 / C20 + S17"
        ),
        PackMetadata(
            id: "hdmi32",
            title: "HDMI 3:2 Output",
            subtitle: "Outputs 3:2 open-gate feed over HDMI to external monitors/recorders.",
            icon: "display",
            defaultStepsHint: "H16 / H17"
        ),
        PackMetadata(
            id: "high_bitrate",
            title: "High-Bitrate Long-GOP (200M / 300M)",
            subtitle: "Unlocks 200 Mbps / 300 Mbps Long-GOP overlays for XAVC HS & XAVC S.",
            icon: "speedometer",
            defaultStepsHint: "B19 / B20"
        ),
        PackMetadata(
            id: "xavc_si",
            title: "XAVC S-I 3840x2560 All-Intra",
            subtitle: "Enables 3:2 open-gate recording in XAVC S-I intra-frame mode.",
            icon: "waveform.path.ecg.rectangle",
            defaultStepsHint: "I19 / I20"
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

            requiredCoreCard

            ForEach(modularCatalog, id: \.id) { meta in
                modularPackCard(meta)
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

    private func modularPackCard(_ meta: PackMetadata) -> some View {
        let manifestPack = appState.selectedBody?.packs[meta.id]
        let isAvailable = appState.selectedBody == nil || manifestPack != nil
        let isEnabled = appState.isPackEnabled(meta.id)
        let stepsDisplay = manifestPack.map { pack in
            let apply = pack.applySteps.joined(separator: ", ")
            let putback = pack.putbackSteps.joined(separator: ", ")
            return "Apply: [\(apply)]  •  Putback: [\(putback)]"
        } ?? meta.defaultStepsHint

        return HStack(alignment: .top, spacing: 12) {
            Image(systemName: meta.icon)
                .font(.title3)
                .foregroundStyle(isEnabled ? Color.accentColor : Color.secondary)
                .frame(width: 28, height: 28)

            VStack(alignment: .leading, spacing: 4) {
                HStack {
                    Text(meta.title)
                        .font(.subheadline.weight(.semibold))
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
                        .disabled(!appState.isChecklistComplete || appState.isRunningPreflight)

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
                        .disabled(!appState.isApplyUnlocked || appState.isApplying)

                        if !appState.isApplyUnlocked {
                            Text("Requires Gate 2 preflight ready == true")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }

                    if let apply = appState.applyResult {
                        VStack(alignment: .leading, spacing: 8) {
                            Text("Ordered .so Steps Executed:")
                                .font(.caption.weight(.semibold))
                                .foregroundStyle(.secondary)

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
            gateCard(
                number: 4,
                title: "Put Back to Stock RAM",
                statusColor: appState.putbackResult != nil ? .green : .secondary,
                statusText: appState.putbackResult != nil ? "Restored" : "Standby"
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
                    .disabled(appState.isPuttingBack)

                    if let putback = appState.putbackResult {
                        VStack(alignment: .leading, spacing: 4) {
                            Text("State: \(putback.state)  •  Steps: \(putback.stepsRun.map(\.step).joined(separator: " -> "))")
                                .font(.caption.monospaced())
                        }
                        .padding(8)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(Color.blue.opacity(0.08))
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
