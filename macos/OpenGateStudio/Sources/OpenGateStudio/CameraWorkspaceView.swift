import OpenGateStudioCore
import SwiftUI

public struct CameraWorkspaceView: View {
    @EnvironmentObject private var appState: AppState
    @State private var showGate1EditorWhenReady: Bool = false
    @State private var showLastResultDetails: Bool = false
    @State private var isPacksExpanded: Bool = false
    @State private var showTechnicalPackIds: Bool = false

    public init() {}

    private var profile: BodySetupProfile {
        BodySetupProfile.forBody(id: appState.selectedBodyId, bodyInfo: appState.selectedBody)
    }

    private var setupCheckedCount: Int {
        [
            appState.checkedFirmwareVersion,
            appState.checkedSdCardSlot1,
            appState.checkedUsbMassStorage,
            appState.checkedMovie24pSettings,
            appState.checkedAppsClosed,
        ].filter { $0 }.count
    }

    public var body: some View {
        ScrollView {
            VStack(spacing: 18) {
                if !appState.isSetupWizardChecklistComplete && !appState.isSetupBannerDismissed {
                    firstTimeSetupBanner
                }

                heroCard

                customizePacksDisclosure

                persistentSafetyFooter
            }
            .frame(maxWidth: 740)
            .frame(maxWidth: .infinity)
            .padding(.horizontal, 24)
            .padding(.vertical, 22)
        }
        .onChange(of: appState.cameraStage) { _, newStage in
            if newStage != .readyToApply {
                showGate1EditorWhenReady = false
            }
        }
    }

    // MARK: - Dismissible First-Time Setup Banner

    private var firstTimeSetupBanner: some View {
        StudioSurface(accent: .blue, padding: 14) {
            HStack(spacing: 12) {
                Image(systemName: "checklist")
                    .font(.title3)
                    .foregroundStyle(.blue)
                    .frame(width: 30, height: 30)
                    .background(Color.blue.opacity(0.12))
                    .clipShape(RoundedRectangle(cornerRadius: 7, style: .continuous))

                VStack(alignment: .leading, spacing: 2) {
                    Text("First-time setup for \(profile.displayName)")
                        .font(.callout.weight(.semibold))
                    Text("Confirm firmware, Slot 1 SD card, USB Mass Storage, and 24p/25p/30p menu settings (\(setupCheckedCount) of 5 checked).")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                Spacer(minLength: 8)

                Button("Open Setup Guide") {
                    appState.showSetupGuideSheet = true
                }
                .buttonStyle(.bordered)
                .controlSize(.small)

                Button {
                    withAnimation(.easeInOut(duration: 0.18)) {
                        appState.isSetupBannerDismissed = true
                    }
                } label: {
                    Image(systemName: "xmark")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.secondary)
                }
                .buttonStyle(.borderless)
                .help("Dismiss setup reminder")
            }
        }
    }

    // MARK: - Primary Camera Hero Card

    private var heroCard: some View {
        let stage = appState.cameraStage

        return StudioSurface(accent: heroAccentBorder(for: stage), padding: 20) {
            VStack(alignment: .leading, spacing: 18) {
                heroHeader(stage: stage)

                activeAlertCallouts(stage: stage)

                if stage != .pinsBlocked && stage != .applied {
                    Divider()
                    gate1Section(stage: stage)
                }

                if stage != .pinsBlocked {
                    Divider()
                    presetSelectorRow
                }

                Divider()

                primaryActionRow(stage: stage)

                if hasSessionSummary {
                    Divider()
                    lastResultSummarySection
                }
            }
        }
    }

    private func heroHeader(stage: CameraWorkflowStage) -> some View {
        HStack(alignment: .top, spacing: 14) {
            Image(systemName: heroIcon(for: stage))
                .font(.system(size: 24, weight: .semibold))
                .foregroundStyle(heroColor(for: stage))
                .frame(width: 44, height: 44)
                .background(heroColor(for: stage).opacity(0.13))
                .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))

            VStack(alignment: .leading, spacing: 4) {
                Text(heroHeadline(for: stage))
                    .font(.title3.weight(.semibold))
                Text(heroSubtitle(for: stage))
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }

            Spacer(minLength: 8)

            VStack(alignment: .trailing, spacing: 6) {
                StudioStatusPill(
                    profile.isFX3 ? "\(profile.displayName) · ILME-FX3 only" : profile.displayName,
                    systemImage: profile.isFX3 ? "exclamationmark.triangle.fill" : "camera.fill",
                    color: profile.isFX3 ? .orange : .secondary
                )

                Button("Setup Guide…") {
                    appState.showSetupGuideSheet = true
                }
                .buttonStyle(.borderless)
                .font(.caption)
                .foregroundStyle(Color.accentColor)
            }
        }
    }

    @ViewBuilder
    private func activeAlertCallouts(stage: CameraWorkflowStage) -> some View {
        if let err = appState.stepperError {
            StudioCallout(
                icon: "xmark.octagon.fill",
                color: .red,
                title: "Action Blocked",
                detail: err
            )
        }

        if appState.isMixedPowerSwitchWarning {
            StudioCallout(
                icon: "battery.0",
                color: .red,
                title: "Warm Power-Switch State Detected",
                detail: "Pull the camera battery for at least 10 seconds to clear residual RAM, boot straight into Stills mode, then run a read-only check."
            )
        } else if stage == .recoveryRequired {
            StudioCallout(
                icon: "exclamationmark.triangle.fill",
                color: .orange,
                title: "Recovery Check Required",
                detail: "A previous live step stopped early or reported an unverified state. Pull the camera battery for >= 10 seconds to restore stock RAM, then run a read-only check."
            )
        }

        if stage == .applied && profile.isFX3 && !fx3PlaybackIsActive {
            StudioCallout(
                icon: "hand.raised.fill",
                color: .orange,
                title: "FX3 Playback Notice",
                detail: "Open-Gate is active without the experimental FX3 Playback patch. Avoid playing back 3:2 clips in-camera; if Unable to Display appears, do not retry."
            )
        }
    }

    @ViewBuilder
    private func gate1Section(stage: CameraWorkflowStage) -> some View {
        if stage == .readyToApply && !showGate1EditorWhenReady {
            HStack(spacing: 8) {
                Image(systemName: "checkmark.circle.fill")
                    .foregroundStyle(.green)
                Text("Cold boot (>= 10s battery pull) & Stills mode confirmed")
                    .font(.callout.weight(.medium))
                Spacer()
                Button("Change") {
                    withAnimation(.easeInOut(duration: 0.16)) {
                        showGate1EditorWhenReady = true
                    }
                }
                .buttonStyle(.borderless)
                .font(.caption)
            }
        } else {
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    Text("Before Connecting")
                        .font(.subheadline.weight(.semibold))
                    Spacer()
                    Text(appState.isChecklistComplete ? "Ready to check" : "Required")
                        .font(.caption.weight(.medium))
                        .foregroundStyle(appState.isChecklistComplete ? .green : .secondary)
                }

                Toggle(
                    "Pulled camera battery for >= 10 seconds (clean RAM baseline)",
                    isOn: $appState.batteryPulled10s
                )
                .font(.callout)

                Toggle(
                    "Camera is in Stills mode (\(profile.stillsShortHint)) before USB plug-in",
                    isOn: $appState.cameraInStillsMode
                )
                .font(.callout)
            }
        }
    }

    private var presetSelectorRow: some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 2) {
                Text("Open-Gate Profile")
                    .font(.subheadline.weight(.semibold))
                Text(presetSummaryText)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Spacer()

            if appState.activePackPreset == nil {
                StudioStatusPill(
                    "Custom (\(appState.selectedPacks.count) packs)",
                    color: .secondary
                )
            }

            Picker("Profile", selection: Binding(
                get: { appState.activePackPreset ?? .safeDaily },
                set: { appState.applyPackPreset($0) }
            )) {
                Text("Safe Daily 3:2").tag(PackPreset.safeDaily)
                Text("Cinema Full").tag(PackPreset.cinemaFull)
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .frame(width: 240)
            .disabled(appState.isLiveSessionActive || appState.isApplying)
        }
    }

    private var presetSummaryText: String {
        switch appState.activePackPreset {
        case .safeDaily:
            return "Recommended — 3840x2560 3:2 MP4, Gyro metadata, and 3:2 LCD framing."
        case .cinemaFull, .reliabilityAudit:
            return "Experimental — Adds HDMI 3:2 output, 200M/300M bitrates, and XAVC S-I."
        case nil:
            return "Custom selection of \(appState.selectedPacks.count) optional feature pack(s)."
        }
    }

    // MARK: - Single Primary Action Row

    private func primaryActionRow(stage: CameraWorkflowStage) -> some View {
        HStack(spacing: 12) {
            primaryActionButton(stage: stage)

            if stage == .applied {
                Button {
                    Task { await appState.putBackToStock() }
                } label: {
                    if appState.isPuttingBack {
                        ProgressView().controlSize(.small)
                    } else {
                        Text("Restore Stock RAM")
                    }
                }
                .buttonStyle(.bordered)
                .controlSize(.large)
                .disabled(appState.isPuttingBack || appState.isLiveSessionActive)
            } else if !appState.isChecklistComplete && (stage == .needsPreflight || stage == .restoredStock || stage == .recoveryRequired) {
                Text("Confirm both checks above to continue")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Spacer()

            overflowMenu(stage: stage)
        }
    }

    @ViewBuilder
    private func primaryActionButton(stage: CameraWorkflowStage) -> some View {
        switch stage {
        case .pinsBlocked:
            Button {
                Task { await appState.verifyPins() }
            } label: {
                actionButtonLabel(
                    title: "Verify Kit Integrity",
                    systemImage: "checkmark.shield.fill",
                    isBusy: appState.isVerifyingPins
                )
            }
            .buttonStyle(.borderedProminent)
            .tint(.orange)
            .controlSize(.large)
            .disabled(appState.isVerifyingPins)

        case .recoveryRequired:
            Button {
                Task { await appState.runPreflight() }
            } label: {
                actionButtonLabel(
                    title: "Run Read-Only Recovery Check",
                    systemImage: "arrow.clockwise.circle.fill",
                    isBusy: appState.isRunningPreflight
                )
            }
            .buttonStyle(.borderedProminent)
            .tint(.orange)
            .controlSize(.large)
            .disabled(!appState.isChecklistComplete || appState.isRunningPreflight || appState.isLiveSessionActive)

        case .readyToApply:
            Button {
                Task { await appState.applySelectedPacks() }
            } label: {
                actionButtonLabel(
                    title: "Apply Open-Gate (3:2)",
                    systemImage: "bolt.shield.fill",
                    isBusy: appState.isApplying
                )
            }
            .buttonStyle(.borderedProminent)
            .tint(.green)
            .controlSize(.large)
            .disabled(!appState.isApplyUnlocked || appState.isApplying || appState.isLiveSessionActive)

        case .applied:
            Button {
                Task { await appState.handleBatterySwapReCheck() }
            } label: {
                actionButtonLabel(
                    title: "Swapped Battery? Re-Check Camera",
                    systemImage: "arrow.triangle.2.circlepath",
                    isBusy: appState.isRunningPreflight
                )
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
            .disabled(appState.isRunningPreflight || appState.isLiveSessionActive)

        case .needsPreflight, .restoredStock:
            Button {
                Task { await appState.runPreflight() }
            } label: {
                actionButtonLabel(
                    title: "Check Camera (Read-Only)",
                    systemImage: "magnifyingglass.circle.fill",
                    isBusy: appState.isRunningPreflight
                )
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
            .disabled(!appState.isChecklistComplete || appState.isRunningPreflight || appState.isLiveSessionActive)
        }
    }

    private func actionButtonLabel(title: String, systemImage: String, isBusy: Bool) -> some View {
        HStack(spacing: 7) {
            if isBusy {
                ProgressView()
                    .controlSize(.small)
            } else {
                Image(systemName: systemImage)
            }
            Text(title)
        }
    }

    private func overflowMenu(stage: CameraWorkflowStage) -> some View {
        Menu {
            Button("Camera Setup Guide…") {
                appState.showSetupGuideSheet = true
            }

            if stage == .readyToApply || stage == .applied {
                Button("Re-Check Camera (Read-Only)") {
                    Task { await appState.runPreflight() }
                }
                .disabled(!appState.isChecklistComplete || appState.isRunningPreflight || appState.isLiveSessionActive)
            }

            Button("Restore Stock RAM") {
                Task { await appState.putBackToStock() }
            }
            .disabled(appState.isPuttingBack || appState.isLiveSessionActive)

            if !appState.offlineMockCamera {
                Divider()
                Button("Sync Latest Camera Session") {
                    Task { await appState.syncLatestCameraSession() }
                }
                .disabled(appState.isSyncingSession || appState.isLiveSessionActive)
            }

            if appState.preparedLiveCommandPath != nil {
                Button("Open Prepared Terminal Fallback") {
                    appState.openPreparedLiveCommand()
                }
            }
        } label: {
            Image(systemName: "ellipsis.circle")
                .font(.title3)
                .foregroundStyle(.secondary)
        }
        .menuStyle(.borderlessButton)
        .frame(width: 28)
        .help("More Camera Actions")
    }

    // MARK: - Last Check / Active Session Summary

    private var hasSessionSummary: Bool {
        appState.applyResult != nil || appState.putbackResult != nil || appState.preflightResult != nil
    }

    private var lastResultSummarySection: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                Image(systemName: lastResultPositive ? "checkmark.seal.fill" : "exclamationmark.triangle.fill")
                    .foregroundStyle(lastResultPositive ? .green : .orange)

                Text(lastResultFriendlySummary)
                    .font(.callout.weight(.medium))

                Spacer()

                StudioStatusPill(
                    appState.lastResultSource?.rawValue ?? (appState.offlineMockCamera ? "Simulation" : "Live USB"),
                    color: appState.offlineMockCamera ? .blue : .green
                )
            }

            DisclosureGroup("Technical Details", isExpanded: $showLastResultDetails) {
                VStack(alignment: .leading, spacing: 6) {
                    if let apply = appState.applyResult {
                        Text("Closing Verify: \(apply.closingDumpVerdict)")
                            .font(.caption.monospaced())
                        if !apply.activePacks.isEmpty {
                            Text("Active Packs: \(apply.activePacks.joined(separator: ", "))")
                                .font(.caption.monospaced())
                                .foregroundStyle(.secondary)
                        }
                        if !apply.stepsRun.isEmpty {
                            Text("Steps: \(apply.stepsRun.map(\.step).joined(separator: " -> "))")
                                .font(.caption.monospaced())
                                .foregroundStyle(.secondary)
                        }
                    } else if let putback = appState.putbackResult {
                        Text("State: \(putback.state)  •  Steps: \(putback.stepsRun.map(\.step).joined(separator: " -> "))")
                            .font(.caption.monospaced())
                            .foregroundStyle(.secondary)
                    } else if let pre = appState.preflightResult {
                        Text("Verdict: \(pre.verdict)  •  State: \(pre.state)  •  Session: \(pre.sessionId)")
                            .font(.caption.monospaced())
                            .foregroundStyle(.secondary)
                    }

                    if let status = appState.liveStatusBanner, !status.isEmpty {
                        Text(status)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
                .padding(.top, 6)
            }
            .font(.caption.weight(.medium))
            .foregroundStyle(.secondary)
        }
    }

    private var lastResultPositive: Bool {
        if let app = appState.applyResult { return app.ok }
        if let put = appState.putbackResult { return put.ok && put.state == "stock" }
        if let pre = appState.preflightResult { return pre.ready }
        return false
    }

    private var lastResultFriendlySummary: String {
        if let app = appState.applyResult, app.ok {
            let names = app.activePacks
                .filter { $0 != "core_open_gate" }
                .map { appState.humanReadablePackTitle(for: $0) }
            if names.isEmpty {
                return "Open-Gate 3:2 is active in camera RAM."
            }
            return "Active in camera RAM: \(names.joined(separator: ", "))"
        }
        if let put = appState.putbackResult {
            return (put.ok && put.state == "stock")
                ? "Camera RAM restored and verified clean stock."
                : "Put-back completed, but stock state is unverified — pull battery >= 10s."
        }
        if let pre = appState.preflightResult {
            return pre.ready
                ? "Camera verified in clean stock RAM and ready to apply Open-Gate."
                : "Preflight blocked: pull battery >= 10s before re-checking."
        }
        return ""
    }

    // MARK: - Customize Feature Packs Disclosure

    private var customizePacksDisclosure: some View {
        let experimentalActive = appState.selectedPacks.contains(where: {
            ["hdmi32", "high_bitrate", "xavc_si", "fx3_playback"].contains($0)
        })

        return StudioSurface(padding: 16) {
            DisclosureGroup(isExpanded: $isPacksExpanded) {
                VStack(alignment: .leading, spacing: 0) {
                    Divider()
                        .padding(.vertical, 10)

                    requiredCorePackRow

                    ForEach(visibleModularPackIds, id: \.self) { packId in
                        Divider()
                            .padding(.vertical, 10)
                        modularPackRow(packId: packId)
                    }

                    Divider()
                        .padding(.vertical, 10)

                    Toggle("Show technical pack & step IDs", isOn: $showTechnicalPackIds)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            } label: {
                HStack(spacing: 10) {
                    Label("Customize Feature Packs", systemImage: "slider.horizontal.3")
                        .font(.headline)

                    Spacer()

                    if experimentalActive {
                        StudioStatusPill("Experimental Active", color: .orange)
                    }

                    Text("\(appState.selectedPacks.count) enabled")
                        .font(.caption.weight(.medium))
                        .foregroundStyle(.secondary)
                }
            }
        }
    }

    private var visibleModularPackIds: [String] {
        AppState.modularPackOrder.filter { packId in
            packId != "fx3_playback" || appState.selectedBody?.packs[packId] != nil
        }
    }

    private var requiredCorePackRow: some View {
        let desc = ModularPackDescriptor.descriptor(for: "core_open_gate", bodyId: appState.selectedBodyId)
        let steps = appState.selectedBody?.packs["core_open_gate"]?.applySteps.joined(separator: " -> ") ?? "L13 -> L5 -> L16"

        return HStack(alignment: .top, spacing: 12) {
            Image(systemName: desc.icon)
                .font(.title3)
                .foregroundStyle(.blue)
                .frame(width: 24)

            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 8) {
                    Text(desc.title)
                        .font(.callout.weight(.semibold))
                    StudioStatusPill("Always Included", color: .blue)
                }
                Text(desc.subtitle)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                if showTechnicalPackIds {
                    Text("core_open_gate · Apply: [\(steps)]")
                        .font(.caption2.monospaced())
                        .foregroundStyle(.secondary)
                }
            }

            Spacer()

            Image(systemName: "lock.fill")
                .font(.caption)
                .foregroundStyle(.secondary)
                .padding(.top, 4)
        }
    }

    private func modularPackRow(packId: String) -> some View {
        let desc = ModularPackDescriptor.descriptor(for: packId, bodyId: appState.selectedBodyId)
        let manifestPack = appState.selectedBody?.packs[packId]
        let isAvailable = appState.selectedBody == nil || manifestPack != nil
        let isEnabled = appState.isPackEnabled(packId)

        return VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .top, spacing: 12) {
                Image(systemName: desc.icon)
                    .font(.title3)
                    .foregroundStyle(isEnabled ? Color.accentColor : Color.secondary)
                    .frame(width: 24)

                VStack(alignment: .leading, spacing: 3) {
                    HStack(spacing: 8) {
                        Text(desc.title)
                            .font(.callout.weight(.semibold))
                        if desc.tier != .recommended {
                            StudioStatusPill(desc.tier.badgeText, color: desc.tier.color)
                        }
                    }

                    Text(desc.subtitle)
                        .font(.caption)
                        .foregroundStyle(.secondary)

                    if showTechnicalPackIds {
                        let applyText = manifestPack?.applySteps.joined(separator: ", ") ?? "—"
                        let putbackText = manifestPack?.putbackSteps.joined(separator: ", ") ?? "—"
                        Text("\(packId) · Apply: [\(applyText)] · Putback: [\(putbackText)]")
                            .font(.caption2.monospaced())
                            .foregroundStyle(.secondary)
                    }
                }

                Spacer()

                Toggle(
                    desc.title,
                    isOn: Binding(
                        get: { isEnabled },
                        set: { appState.setPack(packId, enabled: $0) }
                    )
                )
                .labelsHidden()
                .toggleStyle(.switch)
                .controlSize(.small)
                .disabled(!isAvailable || appState.isLiveSessionActive)
            }

            if packId == "hdmi32" && (isEnabled || profile.isFX3) {
                Text("AF + Anamorphic Tip: Leave FX3 internal De-Squeeze OFF so Sony AF stays active while external HDMI monitors de-squeeze 3:2.")
                    .font(.caption)
                    .foregroundStyle(.blue)
                    .padding(.leading, 36)
            }

            if packId == "fx3_playback" {
                Text("Test one normal 16:9 clip first. If an open-gate clip shows Unable to Display, do NOT retry Playback.")
                    .font(.caption)
                    .foregroundStyle(.orange)
                    .padding(.leading, 36)
            }
        }
        .opacity(isAvailable ? 1.0 : 0.55)
    }

    // MARK: - Footer

    private var persistentSafetyFooter: some View {
        HStack(spacing: 6) {
            Image(systemName: "memorychip")
                .foregroundStyle(.secondary)
            Text("Volatile RAM only — nothing is written to camera firmware or your SD card. Pull battery >= 10s anytime to restore stock.")
                .foregroundStyle(.secondary)
        }
        .font(.caption)
        .multilineTextAlignment(.center)
        .padding(.top, 4)
    }

    // MARK: - Stage Copy & Aesthetics

    private var fx3PlaybackIsActive: Bool {
        if let app = appState.applyResult, app.ok {
            return app.activePacks.contains("fx3_playback")
        }
        return appState.selectedPacks.contains("fx3_playback")
    }

    private func heroAccentBorder(for stage: CameraWorkflowStage) -> Color? {
        switch stage {
        case .pinsBlocked, .recoveryRequired: return .orange
        case .readyToApply, .applied: return .green
        case .restoredStock, .needsPreflight: return nil
        }
    }

    private func heroColor(for stage: CameraWorkflowStage) -> Color {
        switch stage {
        case .pinsBlocked, .recoveryRequired: return .orange
        case .readyToApply, .applied: return .green
        case .restoredStock, .needsPreflight: return .blue
        }
    }

    private func heroIcon(for stage: CameraWorkflowStage) -> String {
        switch stage {
        case .pinsBlocked: return "exclamationmark.shield.fill"
        case .recoveryRequired: return "exclamationmark.triangle.fill"
        case .applied: return "checkmark.seal.fill"
        case .restoredStock: return "arrow.uturn.backward.circle.fill"
        case .readyToApply: return "bolt.shield.fill"
        case .needsPreflight: return "camera.aperture"
        }
    }

    private func heroHeadline(for stage: CameraWorkflowStage) -> String {
        switch stage {
        case .pinsBlocked:
            return "Kit Integrity Check Required"
        case .recoveryRequired:
            return "Recovery Check Required"
        case .applied:
            return "Open-Gate 3:2 Active — Ready to Shoot"
        case .restoredStock:
            return "Camera Restored to Stock RAM"
        case .readyToApply:
            return "Verified Clean RAM — Ready to Apply"
        case .needsPreflight:
            return "Ready to Check \(profile.shortModelName)"
        }
    }

    private func heroSubtitle(for stage: CameraWorkflowStage) -> String {
        switch stage {
        case .pinsBlocked:
            return "Signed kit SHA-256 verification must pass before talking to a camera over Live USB."
        case .recoveryRequired:
            return "Pull the battery for >= 10 seconds, then run a read-only check before applying Open-Gate."
        case .applied:
            return "Keep your camera ON and shoot in 24p, 25p, or 30p. Do not switch to 50p, 60p, or 120p."
        case .restoredStock:
            return "Stock camera RAM was verified. Run a fresh read-only check before applying Open-Gate again."
        case .readyToApply:
            return "Keep your camera ON in Stills mode and click Apply Open-Gate (3:2) to patch volatile RAM."
        case .needsPreflight:
            return "Connect your camera over USB-C in Stills mode (Mass Storage) to verify clean stock RAM first."
        }
    }
}
