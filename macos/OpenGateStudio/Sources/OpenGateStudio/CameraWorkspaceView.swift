import OpenGateStudioCore
import SwiftUI

public struct CameraWorkspaceView: View {
    @EnvironmentObject private var appState: AppState
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
            appState.checkedPowerSaveDisabled,
            appState.checkedMovie24pSettings,
            appState.checkedAppsClosed,
        ].filter { $0 }.count
    }

    public var body: some View {
        let stage = appState.cameraStage

        ScrollView {
            VStack(spacing: 16) {
                topHeader(stage: stage)

                activeAlertCallouts(stage: stage)

                checklistCard(stage: stage)

                primaryActionBlock(stage: stage)

                secondaryActionsRow(stage: stage)

                if isPacksExpanded {
                    featurePacksCard
                }

                persistentSafetyFooter
            }
            .frame(maxWidth: 560)
            .frame(maxWidth: .infinity)
            .padding(.horizontal, 24)
            .padding(.top, 32)
            .padding(.bottom, 24)
        }
    }

    // MARK: - Centered Top Header

    private func topHeader(stage: CameraWorkflowStage) -> some View {
        VStack(spacing: 8) {
            Image(systemName: heroIcon(for: stage))
                .font(.system(size: 22, weight: .semibold))
                .foregroundStyle(heroColor(for: stage))
                .frame(width: 44, height: 44)
                .background(heroColor(for: stage).opacity(0.13))
                .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))

            Text(heroHeadline(for: stage))
                .font(.title2.weight(.semibold))
                .multilineTextAlignment(.center)

            Text(heroSubtitle(for: stage))
                .font(.callout)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.bottom, 4)
    }

    // MARK: - Conditional Alert Callouts

    @ViewBuilder
    private func activeAlertCallouts(stage: CameraWorkflowStage) -> some View {
        if let usb = appState.detectedUsbCamera, usb.isFx3aBlocked {
            StudioCallout(
                icon: "exclamationmark.octagon.fill",
                color: .red,
                title: "Unsupported Camera Detected (ILME-FX3A)",
                detail: usb.warning ?? "ILME-FX3A is not supported by FX3 7.02 kits. Live USB apply is blocked to protect this body."
            )
        }

        if let usb = appState.detectedUsbCamera, usb.detected, !usb.isFx3aBlocked, usb.usbMode == "other" {
            StudioCallout(
                icon: "exclamationmark.triangle.fill",
                color: .orange,
                title: "Camera Connected in Wrong USB Mode",
                detail: "Set MENU > Setup > USB > USB Connection = Mass Storage on your camera (or tap Image Transfer (MSC) on the camera screen) so OpenGate Studio can talk to it."
            )
        }

        if let usb = appState.detectedUsbCamera, usb.detected, usb.usbMode == "service", !appState.isLiveSessionActive {
            StudioCallout(
                icon: "exclamationmark.triangle.fill",
                color: .orange,
                title: "Camera in USB Service Mode",
                detail: "Wait ~5 seconds for USB Mass Storage to return, or unplug USB-C and pull the battery for >= 10 seconds if an earlier session was interrupted."
            )
        }

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
                title: "Warm Power-Switch / Sleep State Detected",
                detail: "Flipping the power switch or waking from Power Save sleep resets sensor RAM to 16:9 while leaving encoder patches active. Set Power Save Start Time = Off, pull the battery for >= 10 seconds, boot straight into Stills mode, and re-check."
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

    // MARK: - Single Checklist Card

    private func checklistCard(stage: CameraWorkflowStage) -> some View {
        StudioSurface(accent: checklistBorderAccent(for: stage), padding: 0) {
            VStack(spacing: 0) {
                cameraUsbRow

                Divider()

                setupChecklistRow

                if stage != .pinsBlocked {
                    Divider()
                    profileRow
                }

                if stage != .pinsBlocked && stage != .applied {
                    Divider()
                    consentRow
                }

                if hasSessionSummary {
                    Divider()
                    lastResultSummarySection
                        .padding(.horizontal, 16)
                        .padding(.vertical, 12)
                }
            }
        }
    }

    private var cameraUsbRow: some View {
        let usb = appState.detectedUsbCamera
        let usbDetected = usb?.detected == true && usb?.isFx3aBlocked != true
        let usbMode = usb?.usbMode ?? "other"
        let badgeIcon = usbDetected ? "cable.connector" : "camera.fill"
        let badgeColor: Color = {
            guard usbDetected else { return .secondary }
            return usbMode == "msc" ? .green : .orange
        }()

        return HStack(spacing: 11) {
            rowIconBadge(systemImage: badgeIcon, color: badgeColor)

            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 6) {
                    Text("Camera USB")
                        .font(.callout.weight(.semibold))

                    if usbDetected {
                        let pillLabel: String = {
                            switch usbMode {
                            case "msc": return "USB Mass Storage"
                            case "service": return "USB Service Mode"
                            default: return "Wrong USB Mode"
                            }
                        }()
                        StudioStatusPill(
                            pillLabel,
                            systemImage: "cable.connector",
                            color: usbMode == "msc" ? .green : .orange
                        )
                    }

                    if profile.isFX3 {
                        StudioStatusPill("ILME-FX3 only", color: .orange)
                    }
                }

                Text("\(profile.shortModelName) · FW \(profile.requiredFirmware)")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Spacer(minLength: 8)

            Button {
                Task { await appState.refreshDetectedUsbCamera() }
            } label: {
                HStack(spacing: 4) {
                    if appState.isDetectingUsbCamera {
                        ProgressView()
                            .controlSize(.mini)
                    }
                    Text("Detect USB")
                }
            }
            .buttonStyle(.bordered)
            .controlSize(.small)
            .disabled(appState.isDetectingUsbCamera || appState.isLiveSessionActive)
            .help("Scan USB bus for a connected Sony camera")
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 13)
    }

    private var setupChecklistRow: some View {
        let complete = appState.isSetupWizardChecklistComplete

        return HStack(spacing: 11) {
            rowIconBadge(
                systemImage: complete ? "checkmark.circle.fill" : "checklist",
                color: complete ? .green : .secondary
            )

            VStack(alignment: .leading, spacing: 2) {
                Text("First-time setup")
                    .font(.callout.weight(.semibold))
                Text(
                    complete
                        ? "All 6 camera menu items checked"
                        : "\(setupCheckedCount) of 6 camera menu items checked"
                )
                .font(.caption)
                .foregroundStyle(.secondary)
            }

            Spacer(minLength: 8)

            Button(complete ? "Review" : "Open Guide") {
                appState.showSetupGuideSheet = true
            }
            .buttonStyle(.borderless)
            .font(.callout.weight(.medium))
            .foregroundStyle(Color.accentColor)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 13)
    }

    private var profileRow: some View {
        HStack(spacing: 11) {
            rowIconBadge(systemImage: "aspectratio", color: .secondary)

            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 6) {
                    Text("Open-Gate profile")
                        .font(.callout.weight(.semibold))
                    if appState.activePackPreset == nil {
                        StudioStatusPill("Custom (\(appState.selectedPacks.count))", color: .secondary)
                    }
                }
                Text(compactPresetSummaryText)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }

            Spacer(minLength: 8)

            Picker("Profile", selection: Binding(
                get: { appState.activePackPreset ?? .safeDaily },
                set: { appState.applyPackPreset($0) }
            )) {
                Text("Safe Daily 3:2").tag(PackPreset.safeDaily)
                Text("Cinema Full").tag(PackPreset.cinemaFull)
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .frame(width: 210)
            .disabled(appState.isLiveSessionActive || appState.isApplying)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 13)
    }

    @ViewBuilder
    private var consentRow: some View {
        if !appState.hasAcceptedExpressSafetyTerms {
            Toggle(
                "I understand OpenGate Studio patches volatile RAM only (24p/25p/30p; battery pull >= 10s restores stock)",
                isOn: $appState.hasAcceptedExpressSafetyTerms
            )
            .font(.callout)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 16)
            .padding(.vertical, 13)
        } else {
            HStack(spacing: 8) {
                Image(systemName: "checkmark.circle.fill")
                    .foregroundStyle(.green)
                    .font(.caption)
                Text("Cold boot >=10s · Stills mode · Mass Storage · 24p/25p/30p only")
                    .font(.caption.weight(.medium))
                    .foregroundStyle(.secondary)
                Spacer()
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 11)
        }
    }

    private func rowIconBadge(systemImage: String, color: Color) -> some View {
        Image(systemName: systemImage)
            .font(.callout.weight(.medium))
            .foregroundStyle(color)
            .frame(width: 28, height: 28)
            .background(Color.primary.opacity(0.05))
            .clipShape(RoundedRectangle(cornerRadius: 7, style: .continuous))
    }

    private var compactPresetSummaryText: String {
        let isBionzX = appState.selectedBodyId == "a7c_203" || appState.selectedBodyId == "zve10_203"
        switch appState.activePackPreset {
        case .safeDaily:
            if isBionzX {
                return "6000x4000 3:2 readout in XAVC S 4K 24p"
            }
            return "3840x2560 MP4, Gyro, 3:2 LCD"
        case .cinemaFull, .reliabilityAudit:
            if isBionzX {
                return "Native 3840x2560 3:2 H.264 raster & MP4"
            }
            return "HDMI 3:2, 200M/300M bitrates, XAVC S-I"
        case nil:
            return "\(appState.selectedPacks.count) custom feature pack(s) enabled"
        }
    }

    // MARK: - Primary Action Block

    private func primaryActionBlock(stage: CameraWorkflowStage) -> some View {
        VStack(spacing: 8) {
            primaryActionButton(stage: stage)

            if stage == .applied {
                Button {
                    Task { await appState.runExpressPutback() }
                } label: {
                    HStack(spacing: 6) {
                        if appState.isPuttingBack {
                            ProgressView().controlSize(.small)
                        } else {
                            Text("Restore Stock RAM")
                        }
                    }
                    .frame(maxWidth: .infinity)
                }
                .buttonStyle(.bordered)
                .controlSize(.large)
                .disabled(appState.isPuttingBack || appState.isLiveSessionActive)
            }
        }
    }

    @ViewBuilder
    private func primaryActionButton(stage: CameraWorkflowStage) -> some View {
        let fx3aBlocked = !appState.offlineMockCamera && (appState.detectedUsbCamera?.isFx3aBlocked == true)

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
                Task { await appState.handleRecoveryExpressCheckAndApply() }
            } label: {
                actionButtonLabel(
                    title: "Pulled Battery >=10s — Check & Apply (1-Click)",
                    systemImage: "arrow.clockwise.circle.fill",
                    isBusy: appState.isApplying || appState.isRunningPreflight
                )
            }
            .buttonStyle(.borderedProminent)
            .tint(.orange)
            .controlSize(.large)
            .disabled(fx3aBlocked || appState.isApplying || appState.isRunningPreflight || appState.isLiveSessionActive)

        case .needsPreflight, .restoredStock, .readyToApply:
            Button {
                Task { await appState.runExpressApply() }
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
            .disabled(fx3aBlocked || appState.isApplying || appState.isLiveSessionActive)

        case .applied:
            Button {
                Task { await appState.handleBatterySwapExpressReapply() }
            } label: {
                actionButtonLabel(
                    title: "Swapped Battery? Re-Apply (1-Click)",
                    systemImage: "arrow.triangle.2.circlepath",
                    isBusy: appState.isApplying
                )
            }
            .buttonStyle(.borderedProminent)
            .tint(.green)
            .controlSize(.large)
            .disabled(fx3aBlocked || appState.isApplying || appState.isLiveSessionActive)
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
        .frame(maxWidth: .infinity)
    }

    // MARK: - Secondary Actions Row

    private func secondaryActionsRow(stage: CameraWorkflowStage) -> some View {
        let experimentalActive = appState.selectedPacks.contains(where: {
            ["hdmi32", "high_bitrate", "xavc_si", "fx3_playback"].contains($0)
        })

        return HStack(spacing: 12) {
            Button {
                withAnimation(.easeInOut(duration: 0.18)) {
                    isPacksExpanded.toggle()
                }
            } label: {
                HStack(spacing: 6) {
                    Text("Customize Feature Packs (\(appState.selectedPacks.count) enabled)")
                    if experimentalActive {
                        StudioStatusPill("Experimental", color: .orange)
                    }
                }
            }
            .buttonStyle(.borderless)
            .font(.callout.weight(.medium))
            .foregroundStyle(Color.accentColor)

            Text("·")
                .foregroundStyle(.secondary)

            overflowMenu(stage: stage)
        }
    }

    private func overflowMenu(stage: CameraWorkflowStage) -> some View {
        Menu {
            Button("Camera Setup Guide…") {
                appState.showSetupGuideSheet = true
            }

            Button("Check Camera Only (Read-Only)") {
                Task { await appState.runPreflight() }
            }
            .disabled(appState.isRunningPreflight || appState.isLiveSessionActive)

            Button("Step-by-Step Apply + Movie Dump") {
                Task { await appState.runLegacyStepByStepApply() }
            }
            .disabled(appState.isApplying || appState.isLiveSessionActive)

            Button("Restore Stock RAM") {
                Task { await appState.runExpressPutback() }
            }
            .disabled(appState.isPuttingBack || appState.isLiveSessionActive)

            Divider()

            Button("Reset One-Time Safety Prompt") {
                appState.resetExpressSafetyTerms()
            }
            .disabled(!appState.hasAcceptedExpressSafetyTerms || appState.isLiveSessionActive)

            if !appState.offlineMockCamera {
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
            HStack(spacing: 4) {
                Text("More Actions")
                Image(systemName: "chevron.down")
                    .font(.caption2.weight(.semibold))
            }
            .font(.callout)
            .foregroundStyle(.secondary)
        }
        .menuStyle(.borderlessButton)
        .fixedSize()
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

    // MARK: - Expandable Feature Packs Card

    private var featurePacksCard: some View {
        StudioSurface(padding: 16) {
            VStack(alignment: .leading, spacing: 0) {
                HStack {
                    Label("Feature Packs", systemImage: "slider.horizontal.3")
                        .font(.headline)
                    Spacer()
                    Button("Done") {
                        withAnimation(.easeInOut(duration: 0.18)) {
                            isPacksExpanded = false
                        }
                    }
                    .buttonStyle(.borderless)
                    .font(.caption.weight(.medium))
                    .foregroundStyle(Color.accentColor)
                }

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

    private func checklistBorderAccent(for stage: CameraWorkflowStage) -> Color? {
        switch stage {
        case .pinsBlocked, .recoveryRequired: return .orange
        case .readyToApply, .applied, .needsPreflight, .restoredStock: return nil
        }
    }

    private func heroColor(for stage: CameraWorkflowStage) -> Color {
        switch stage {
        case .pinsBlocked, .recoveryRequired: return .orange
        case .readyToApply, .applied, .needsPreflight, .restoredStock: return .green
        }
    }

    private func heroIcon(for stage: CameraWorkflowStage) -> String {
        switch stage {
        case .pinsBlocked: return "exclamationmark.shield.fill"
        case .recoveryRequired: return "exclamationmark.triangle.fill"
        case .applied: return "checkmark.seal.fill"
        case .restoredStock: return "arrow.uturn.backward.circle.fill"
        case .readyToApply, .needsPreflight: return "bolt.shield.fill"
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
        case .readyToApply, .needsPreflight:
            return "Ready for Open-Gate on \(profile.shortModelName)"
        }
    }

    private func heroSubtitle(for stage: CameraWorkflowStage) -> String {
        switch stage {
        case .pinsBlocked:
            return "Signed kit SHA-256 verification must pass before talking to a camera over Live USB."
        case .recoveryRequired:
            return "Pull the battery for >= 10 seconds to clear residual RAM, then click Check & Apply."
        case .applied:
            return "Unplug USB-C, switch to Movie (24p, 25p, or 30p) and shoot. Keep Power Save = Off so the camera doesn't sleep; do not switch to 50p, 60p, or 120p."
        case .restoredStock:
            return "Stock camera RAM was verified. Click Apply Open-Gate (3:2) anytime to patch volatile RAM again."
        case .readyToApply, .needsPreflight:
            return "Connect in Stills mode (Mass Storage) and apply to volatile RAM."
        }
    }
}
