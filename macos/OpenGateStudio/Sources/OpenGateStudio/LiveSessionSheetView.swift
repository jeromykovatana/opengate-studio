import OpenGateStudioCore
import SwiftUI

public struct LiveSessionSheetView: View {
    @EnvironmentObject private var appState: AppState
    @State private var pulseActive: Bool = false
    @State private var showConfirmAdvanced: Bool = false

    public init() {}

    public var body: some View {
        Group {
            if let session = appState.activeLiveSession {
                VStack(spacing: 0) {
                    sheetHeader(session)
                    Divider()

                    if session.phase == .confirming {
                        confirmingBody(session)
                    } else {
                        executionBody(session)
                    }

                    Divider()
                    sheetFooter(session)
                }
                .frame(minWidth: 620, idealWidth: 660, minHeight: 500, idealHeight: 600)
                .interactiveDismissDisabled(session.phase == .running)
                .onAppear {
                    withAnimation(.easeInOut(duration: 0.95).repeatForever(autoreverses: true)) {
                        pulseActive = true
                    }
                }
            } else {
                EmptyView()
            }
        }
    }

    // MARK: - Header

    private func sheetHeader(_ session: LiveSessionPresentation) -> some View {
        HStack(alignment: .center, spacing: 12) {
            Image(systemName: actionIcon(for: session.action))
                .font(.title2)
                .foregroundStyle(actionAccent(for: session.action))
                .frame(width: 34, height: 34)
                .background(actionAccent(for: session.action).opacity(0.14))
                .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))

            VStack(alignment: .leading, spacing: 2) {
                Text(session.actionTitle)
                    .font(.headline)
                HStack(spacing: 6) {
                    Text(session.cameraDisplayName)
                        .font(.caption.weight(.semibold))
                    Text("·")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Text("FW \(session.requiredFirmware)")
                        .font(.caption.monospacedDigit().weight(.semibold))
                        .foregroundStyle(session.bodyId == "fx3_702" ? .orange : .green)
                }
            }

            Spacer()

            StudioStatusPill("Volatile RAM Only", systemImage: "memorychip", color: .blue)
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 14)
        .background(.bar)
    }

    // MARK: - Confirming Phase

    private func confirmingBody(_ session: LiveSessionPresentation) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                StudioSurface(padding: 15) {
                    VStack(alignment: .leading, spacing: 12) {
                        HStack {
                            Text("Session Summary")
                                .font(.subheadline.weight(.semibold))
                            Spacer()
                            if session.isExpressAction {
                                StudioStatusPill(
                                    expressBadgeText(for: session),
                                    systemImage: "bolt.fill",
                                    color: .green
                                )
                            } else {
                                let stepNoun = session.estimatedStepCount == 1 ? "step" : "steps"
                                let suffix = session.action == .apply
                                    ? " + closing verify"
                                    : (session.action == .putback ? " + stock verify" : "")
                                Text("\(session.estimatedStepCount) \(stepNoun)\(suffix)")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                        }

                        HStack(spacing: 22) {
                            labeledBadge(title: "Camera", value: session.cameraDisplayName)
                            labeledBadge(title: "Required Firmware", value: session.requiredFirmware)
                            labeledBadge(
                                title: "Access",
                                value: session.requiresVolatileRamConfirmation ? "Volatile RAM Write" : "Read-Only"
                            )
                        }

                        if (session.action == .apply || session.action == .expressApply) && !session.selectedPacks.isEmpty {
                            Divider()
                            VStack(alignment: .leading, spacing: 6) {
                                Text("Enabled Features")
                                    .font(.caption.weight(.semibold))
                                    .foregroundStyle(.secondary)
                                ScrollView(.horizontal, showsIndicators: false) {
                                    HStack(spacing: 6) {
                                        StudioStatusPill(appState.humanReadablePackTitle(for: "core_open_gate"), color: .blue)
                                        ForEach(session.selectedPacks.filter { $0 != "core_open_gate" }, id: \.self) { pack in
                                            StudioStatusPill(appState.humanReadablePackTitle(for: pack), color: .secondary)
                                        }
                                    }
                                }
                            }
                        }
                    }
                }

                // Safety Reminders
                VStack(alignment: .leading, spacing: 8) {
                    if session.requiresVolatileRamConfirmation {
                        safetyCalloutRow(
                            icon: "bolt.shield.fill",
                            color: .blue,
                            text: "Writes to volatile RAM only — zero eMMC flash or SD card writes. Keep the camera ON between USB replug prompts; pull the battery for >= 10 seconds anytime to restore stock."
                        )
                        safetyCalloutRow(
                            icon: "film",
                            color: .orange,
                            text: (session.bodyId == "a7c_203" || session.bodyId == "zve10_203")
                                ? "Shoot XAVC S 4K 24p (23.98p) 100M while Open-Gate is active (1.185x vertical de-squeeze in post unless True 3840x2560 Raster is enabled)."
                                : "Shoot 24p (23.98p), 25p (PAL), or 30p (29.97p) only while Open-Gate is active. Do not switch to 50p, 60p, or 120p."
                        )
                        if session.bodyId == "fx3_702" {
                            safetyCalloutRow(
                                icon: "hand.raised.fill",
                                color: .red,
                                text: "FX3: Verify Model Name is ILME-FX3 (NOT ILME-FX3A). Do not retry Playback if an open-gate clip says Unable to Display."
                            )
                        }
                    } else {
                        safetyCalloutRow(
                            icon: "checkmark.shield.fill",
                            color: .green,
                            text: "Read-only inspection checks camera RAM without writing anything. Connect the camera in Stills mode (Mass Storage) when prompted."
                        )
                    }
                }
                .padding(13)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(Color.blue.opacity(0.06))
                .overlay(
                    RoundedRectangle(cornerRadius: 10, style: .continuous)
                        .strokeBorder(Color.blue.opacity(0.20), lineWidth: 1)
                )
                .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))

                // Mandatory Safety Confirmation Switches
                StudioSurface(accent: session.canAuthorizeAndStart ? .green : .orange, padding: 15) {
                    VStack(alignment: .leading, spacing: 12) {
                        Text(session.isExpressAction ? "One-Time Express Safety Consent" : "Confirm Before Authorizing")
                            .font(.subheadline.weight(.semibold))

                        if session.isExpressAction {
                            Toggle(isOn: Binding(
                                get: { appState.activeLiveSession?.confirmedVolatileRam ?? false },
                                set: { newValue in
                                    appState.activeLiveSession?.confirmedVolatileRam = newValue
                                    appState.activeLiveSession?.confirmedFirmwareAndUsb = newValue
                                }
                            )) {
                                VStack(alignment: .leading, spacing: 2) {
                                    Text("I understand OpenGate Studio patches volatile RAM only (shoot 24p/25p/30p; battery pull >= 10s restores stock)")
                                        .font(.callout.weight(.medium))
                                    Text("Saved once for future 1-click runs. Connect camera in Stills mode (USB Mass Storage, FW \(session.requiredFirmware)).")
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                }
                            }
                            .toggleStyle(.switch)
                        } else {
                            Toggle(isOn: Binding(
                                get: { appState.activeLiveSession?.confirmedFirmwareAndUsb ?? false },
                                set: { appState.activeLiveSession?.confirmedFirmwareAndUsb = $0 }
                            )) {
                                VStack(alignment: .leading, spacing: 2) {
                                    Text("I verified camera firmware \(session.requiredFirmware) and USB Connection = Mass Storage")
                                        .font(.callout.weight(.medium))
                                    Text("Checked in MENU > Setup > Setup Option > Version and USB Connection Mode.")
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                }
                            }
                            .toggleStyle(.switch)

                            if session.requiresVolatileRamConfirmation {
                                Divider()
                                Toggle(isOn: Binding(
                                    get: { appState.activeLiveSession?.confirmedVolatileRam ?? false },
                                    set: { appState.activeLiveSession?.confirmedVolatileRam = $0 }
                                )) {
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text("I understand this writes volatile RAM only (keep camera ON between steps; battery pull >= 10s restores stock)")
                                            .font(.callout.weight(.medium))
                                        Text("Nothing is flashed to permanent camera memory or written to your SD card.")
                                            .font(.caption)
                                            .foregroundStyle(.secondary)
                                    }
                                }
                                .toggleStyle(.switch)
                            }
                        }
                    }
                }

                HStack(spacing: 8) {
                    Image(systemName: "touchid")
                        .foregroundStyle(.secondary)
                    Text("macOS will ask for Touch ID or your administrator password once to temporarily release USB Mass Storage.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                DisclosureGroup("Advanced & Step Details", isExpanded: $showConfirmAdvanced) {
                    VStack(alignment: .leading, spacing: 10) {
                        if !session.estimatedStepsPreview.isEmpty {
                            VStack(alignment: .leading, spacing: 3) {
                                Text("Planned Step Order")
                                    .font(.caption.weight(.semibold))
                                    .foregroundStyle(.secondary)
                                Text(session.estimatedStepsPreview.joined(separator: "  →  "))
                                    .font(.caption.monospaced())
                                    .textSelection(.enabled)
                            }
                        }

                        Button {
                            Task { await appState.launchTerminalFallbackFromSheet() }
                        } label: {
                            Label("Use Terminal Fallback Instead", systemImage: "terminal")
                        }
                        .buttonStyle(.bordered)
                        .controlSize(.small)
                    }
                    .padding(.top, 8)
                }
                .font(.caption.weight(.medium))
                .foregroundStyle(.secondary)
            }
            .padding(20)
        }
    }

    // MARK: - Running / Finished / Cancelled / Failed Phase

    private func executionBody(_ session: LiveSessionPresentation) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                progressHeaderCard(session)

                if session.phase == .running, let banner = session.activeBanner {
                    actionBannerView(banner)
                }

                if session.phase == .finished {
                    finishedOutcomeBanner(session)
                } else if session.phase == .cancelled {
                    cancelledOutcomeBanner(session)
                } else if session.phase == .failed {
                    failedOutcomeBanner(session)
                }

                stepsListCard(session)

                liveLogDisclosure(session)
            }
            .padding(20)
        }
    }

    private func progressHeaderCard(_ session: LiveSessionPresentation) -> some View {
        StudioSurface(accent: phaseColor(session), padding: 14) {
            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    HStack(spacing: 8) {
                        if session.phase == .running {
                            ProgressView()
                                .controlSize(.small)
                        } else {
                            Image(systemName: phaseIcon(session))
                                .foregroundStyle(phaseColor(session))
                        }
                        Text(phaseHeadline(session))
                            .font(.subheadline.weight(.semibold))
                    }
                    Spacer()
                    if session.isExpressAction {
                        StudioStatusPill(
                            expressBadgeText(for: session),
                            systemImage: "bolt.fill",
                            color: .green
                        )
                    }
                    if !session.steps.isEmpty {
                        Text("\(session.completedProgressUnits) / \(session.steps.count + (session.includesClosingDump ? 1 : 0)) steps")
                            .font(.caption.monospacedDigit().weight(.semibold))
                            .foregroundStyle(.secondary)
                    }
                }

                ProgressView(value: session.progressFraction)
                    .progressViewStyle(.linear)
                    .tint(phaseColor(session))
            }
        }
    }

    @ViewBuilder
    private func actionBannerView(_ banner: LiveActionBanner) -> some View {
        switch banner {
        case .awaitingAdminAuth:
            HStack(alignment: .center, spacing: 12) {
                Image(systemName: "lock.shield.fill")
                    .font(.title2)
                    .foregroundStyle(.blue)
                VStack(alignment: .leading, spacing: 2) {
                    Text("Waiting for macOS Administrator Authorization")
                        .font(.headline)
                    Text("Approve the native macOS Touch ID or password prompt to start the Live USB session.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                ProgressView().controlSize(.small)
            }
            .padding(16)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color.blue.opacity(0.10))
            .overlay(
                RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .stroke(Color.blue.opacity(0.40), lineWidth: 1.5)
            )
            .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))

        case .connectInitialDrive(_, let detail, let stepId):
            HStack(alignment: .top, spacing: 14) {
                Image(systemName: "cable.connector")
                    .font(.system(size: 28, weight: .semibold))
                    .foregroundStyle(.white)
                    .frame(width: 46, height: 46)
                    .background(Color.blue)
                    .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))

                VStack(alignment: .leading, spacing: 4) {
                    HStack {
                        StudioStatusPill("ACTION REQUIRED", color: .blue)
                        if let stepId, !stepId.isEmpty {
                            Text(stepId)
                                .font(.caption2.monospaced())
                                .foregroundStyle(.secondary)
                        }
                    }
                    Text("Connect USB-C in Stills Mode (Mass Storage)")
                        .font(.title3.weight(.bold))
                    Text(detail)
                        .font(.callout)
                        .foregroundStyle(.secondary)
                }
                Spacer()
            }
            .padding(16)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color.blue.opacity(0.14))
            .overlay(
                RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .stroke(Color.blue.opacity(0.75), lineWidth: 2)
            )
            .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))

        case .replugUsbDrive(_, let detail, let stepId):
            HStack(alignment: .top, spacing: 14) {
                Image(systemName: "arrow.triangle.2.circlepath.circle.fill")
                    .font(.system(size: 30, weight: .semibold))
                    .foregroundStyle(.white)
                    .frame(width: 48, height: 48)
                    .background(Color.orange)
                    .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                    .scaleEffect(pulseActive ? 1.06 : 0.96)

                VStack(alignment: .leading, spacing: 5) {
                    HStack(spacing: 8) {
                        Text("UNPLUG & REPLUG USB-C")
                            .font(.caption2.weight(.heavy))
                            .padding(.horizontal, 8)
                            .padding(.vertical, 2)
                            .background(Color.orange)
                            .foregroundStyle(.white)
                            .clipShape(Capsule())

                        StudioStatusPill("KEEP CAMERA ON", color: .red)

                        if let stepId, !stepId.isEmpty {
                            Text("Next: \(stepId)")
                                .font(.caption2.monospaced())
                                .foregroundStyle(.secondary)
                        }
                    }

                    Text("Unplug USB-C and Plug Right Back In — Keep Camera ON!")
                        .font(.title3.weight(.bold))
                    Text(detail)
                        .font(.callout)
                        .foregroundStyle(.secondary)
                }
                Spacer()
            }
            .padding(16)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color.orange.opacity(pulseActive ? 0.22 : 0.12))
            .overlay(
                RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .stroke(Color.orange.opacity(pulseActive ? 0.95 : 0.55), lineWidth: 2.5)
            )
            .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))

        case .switchToMovieMode(_, let detail, let hint):
            HStack(alignment: .top, spacing: 14) {
                Image(systemName: "video.fill")
                    .font(.system(size: 28, weight: .semibold))
                    .foregroundStyle(.white)
                    .frame(width: 48, height: 48)
                    .background(
                        LinearGradient(
                            colors: [Color.purple, Color.blue],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        )
                    )
                    .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                    .scaleEffect(pulseActive ? 1.06 : 0.96)

                VStack(alignment: .leading, spacing: 5) {
                    HStack(spacing: 8) {
                        Text("SWITCH TO MOVIE MODE")
                            .font(.caption2.weight(.heavy))
                            .padding(.horizontal, 8)
                            .padding(.vertical, 2)
                            .background(Color.purple)
                            .foregroundStyle(.white)
                            .clipShape(Capsule())

                        StudioStatusPill("24p / 25p / 30p ONLY", color: .blue)
                    }

                    Text("Unplug USB-C → Switch Camera to MOVIE Mode (24p/25p/30p) → Replug USB-C")
                        .font(.title3.weight(.bold))
                    Text(detail)
                        .font(.callout)
                        .foregroundStyle(.secondary)
                    if let hint, !hint.isEmpty {
                        Text("Camera control: \(hint)")
                            .font(.caption.weight(.medium))
                            .foregroundStyle(.purple)
                    }
                }
                Spacer()
            }
            .padding(16)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(
                LinearGradient(
                    colors: [
                        Color.purple.opacity(pulseActive ? 0.20 : 0.12),
                        Color.blue.opacity(pulseActive ? 0.18 : 0.10)
                    ],
                    startPoint: .leading,
                    endPoint: .trailing
                )
            )
            .overlay(
                RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .stroke(Color.purple.opacity(pulseActive ? 0.90 : 0.50), lineWidth: 2.5)
            )
            .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
        }
    }

    @ViewBuilder
    private func finishedOutcomeBanner(_ session: LiveSessionPresentation) -> some View {
        let isReady = session.completionReady ?? false
        let accent: Color = isReady ? .green : .red

        let headline: String = {
            switch session.action {
            case .apply:
                return isReady
                    ? "Open-Gate Applied — Ready to Shoot (24p / 25p / 30p)"
                    : "Apply Completed — Verification Needs Review"
            case .expressApply:
                return isReady
                    ? "Open-Gate 3:2 Active — Unplug USB-C, Switch to Movie (24p/25p/30p) & Shoot!"
                    : "Express Apply Completed — Verification Needs Review"
            case .preflight, .dump:
                return isReady
                    ? "Camera Verified Clean RAM — Ready to Apply"
                    : "Preflight Blocked — Camera Not Ready"
            case .putback, .expressPutback:
                return isReady
                    ? "Camera Restored & Verified Stock RAM"
                    : "Put Back Completed — Stock Verification Unconfirmed"
            }
        }()

        let subtitle: String = {
            switch session.action {
            case .apply, .expressApply:
                return isReady
                    ? "Keep the camera ON while shooting 24p / 25p / 30p open-gate clips. Pull battery >= 10s anytime to return to stock."
                    : (session.completionVerdict ?? "Check the closing verification verdict before recording.")
            case .preflight, .dump:
                return isReady
                    ? "You can now apply Open-Gate 3:2 in the Camera workspace."
                    : "Pull the battery for >= 10 seconds to clear residual RAM state, then run Read-Only Check again."
            case .putback, .expressPutback:
                return isReady
                    ? "Volatile RAM patches were reversed and verified back to stock state."
                    : "Closing stock verification did not pass. Pull battery >= 10s to guarantee clean stock RAM."
            }
        }()

        StudioSurface(accent: accent, padding: 14) {
            VStack(alignment: .leading, spacing: 8) {
                HStack(spacing: 10) {
                    Image(systemName: isReady ? "checkmark.seal.fill" : "exclamationmark.triangle.fill")
                        .font(.title2)
                        .foregroundStyle(accent)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(headline)
                            .font(.headline)
                            .foregroundStyle(accent)
                        Text(subtitle)
                            .font(.callout)
                    }
                    Spacer()
                }

                if isReady && session.action == .expressApply && session.bodyId == "a7s3_501" {
                    Text("Tip: On a7S III, if Movie live view looks purple on first switch, tap Record start/stop once.")
                        .font(.caption.weight(.medium))
                        .foregroundStyle(.purple)
                }

                if let verdict = session.completionVerdict, !verdict.isEmpty {
                    Text("Verdict: \(verdict)\(session.completionSessionId.map { "  ·  Session: \($0)" } ?? "")")
                        .font(.caption.monospaced())
                        .foregroundStyle(.secondary)
                }
            }
        }
    }

    private func cancelledOutcomeBanner(_ session: LiveSessionPresentation) -> some View {
        let color: Color = session.wasAdminAuthCancelled ? .blue : .orange
        let icon: String = session.wasAdminAuthCancelled ? "info.circle.fill" : "hand.raised.circle.fill"
        let title: String = session.wasAdminAuthCancelled
            ? "Administrator authorization cancelled — nothing was sent to the camera"
            : "Session Cancelled Safely"
        let detail: String = (!session.wasAdminAuthCancelled ? session.cancelMessage : nil)
            ?? "You can click Try Again to re-authorize, or Close to return."

        return StudioCallout(icon: icon, color: color, title: title, detail: detail)
    }

    private func failedOutcomeBanner(_ session: LiveSessionPresentation) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            StudioCallout(
                icon: "xmark.octagon.fill",
                color: .red,
                title: "\(session.actionTitle) Stopped With an Error",
                detail: session.failureMessage ?? "An unexpected error occurred. Expand Live Output Log for details."
            )

            if session.leftBehindWarning {
                StudioCallout(
                    icon: "battery.25",
                    color: .orange,
                    title: "Volatile RAM May Still Contain Partial Steps",
                    detail: "Pull the camera battery for >= 10 seconds to restore clean stock RAM before retrying."
                )
            }
        }
    }

    // MARK: - Live Step Cards

    private func stepsListCard(_ session: LiveSessionPresentation) -> some View {
        StudioSurface(padding: 14) {
            VStack(alignment: .leading, spacing: 10) {
                Text("Progress")
                    .font(.subheadline.weight(.semibold))

                if session.steps.isEmpty && !session.includesClosingDump {
                    HStack(spacing: 8) {
                        if session.phase == .running {
                            ProgressView().controlSize(.small)
                            Text("Preparing step plan…")
                                .font(.callout)
                                .foregroundStyle(.secondary)
                        } else {
                            Text("No steps were executed.")
                                .font(.callout)
                                .foregroundStyle(.secondary)
                        }
                    }
                    .padding(.vertical, 4)
                } else {
                    VStack(spacing: 8) {
                        ForEach(session.steps) { step in
                            stepRow(
                                code: step.id,
                                indexLabel: "\(step.index)",
                                summary: step.summary,
                                status: step.status
                            )
                        }

                        if session.includesClosingDump {
                            let isStockCheck = session.closingKind == "stock_check" || session.action == .putback
                            stepRow(
                                code: isStockCheck ? "CHECK" : "VERIFY",
                                indexLabel: "\(session.steps.count + 1)",
                                summary: isStockCheck
                                    ? "Closing read-only stock verification check"
                                    : "Closing Movie-mode RAM verification dump",
                                status: session.closingDumpStatus ?? .pending
                            )
                        }
                    }
                }
            }
        }
    }

    private func stepRow(code: String, indexLabel: String, summary: String, status: LiveStepStatus) -> some View {
        let rowAccent = stepStatusColor(status)
        return HStack(spacing: 10) {
            Text(indexLabel)
                .font(.caption2.monospacedDigit().weight(.semibold))
                .foregroundStyle(.secondary)
                .frame(width: 18, alignment: .trailing)

            Text(summary)
                .font(.callout)
                .lineLimit(2)

            Spacer()

            Text(code)
                .font(.caption2.monospaced())
                .foregroundStyle(.secondary)

            stepStatusAccessory(status)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 8)
        .background(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .fill(stepRowBackground(status))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .strokeBorder(rowAccent.opacity(stepRowBorderOpacity(status)), lineWidth: 1)
        )
    }

    @ViewBuilder
    private func stepStatusAccessory(_ status: LiveStepStatus) -> some View {
        switch status {
        case .pending:
            Image(systemName: "circle")
                .font(.caption)
                .foregroundStyle(.secondary)

        case .waitingDrive(let first):
            StudioStatusPill(
                first ? "Connect USB" : "Replug USB",
                systemImage: first ? "cable.connector" : "arrow.triangle.2.circlepath",
                color: first ? .blue : .orange
            )

        case .active:
            HStack(spacing: 5) {
                ProgressView().controlSize(.small)
                Text("Running")
                    .font(.caption.weight(.medium))
                    .foregroundStyle(.blue)
            }

        case .done(let outcome):
            HStack(spacing: 4) {
                Image(systemName: "checkmark.circle.fill")
                    .foregroundStyle(.green)
                Text(outcome)
                    .font(.caption.weight(.medium))
                    .foregroundStyle(.green)
            }

        case .failed(let msg):
            HStack(spacing: 4) {
                Image(systemName: "xmark.circle.fill")
                    .foregroundStyle(.red)
                Text(msg ?? "Failed")
                    .font(.caption.weight(.medium))
                    .foregroundStyle(.red)
                    .lineLimit(1)
            }
        }
    }

    // MARK: - Live Output Log Disclosure

    private func liveLogDisclosure(_ session: LiveSessionPresentation) -> some View {
        StudioSurface(padding: 12) {
            DisclosureGroup(
                isExpanded: Binding(
                    get: { appState.activeLiveSession?.isLogExpanded ?? false },
                    set: { appState.activeLiveSession?.isLogExpanded = $0 }
                )
            ) {
                ScrollView {
                    Text(session.logText.isEmpty ? "Waiting for live output…" : session.logText)
                        .font(.caption.monospaced())
                        .foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .textSelection(.enabled)
                        .padding(10)
                }
                .frame(minHeight: 110, maxHeight: 180)
                .background(Color(nsColor: .textBackgroundColor))
                .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                .padding(.top, 6)
            } label: {
                HStack {
                    Label("Live Output Log", systemImage: "text.alignleft")
                        .font(.subheadline.weight(.semibold))
                    Spacer()
                    let lineCount = session.logText.isEmpty ? 0 : session.logText.split(whereSeparator: \.isNewline).count
                    Text("\(lineCount) lines")
                        .font(.caption2.monospacedDigit())
                        .foregroundStyle(.secondary)
                }
            }
        }
    }

    // MARK: - Footer

    private func sheetFooter(_ session: LiveSessionPresentation) -> some View {
        HStack(spacing: 10) {
            switch session.phase {
            case .confirming:
                Button("Cancel") {
                    appState.dismissLiveSessionSheet()
                }
                .keyboardShortcut(.cancelAction)

                Spacer()

                Button {
                    Task { await appState.authorizeAndStartLiveSession() }
                } label: {
                    Label("Authorize & Start \(session.actionTitle)", systemImage: "lock.open.fill")
                }
                .buttonStyle(.borderedProminent)
                .tint(actionAccent(for: session.action))
                .controlSize(.large)
                .disabled(!session.canAuthorizeAndStart)

            case .running:
                if session.isCancelling {
                    HStack(spacing: 8) {
                        ProgressView().controlSize(.small)
                        Text("Cancelling safely before next step…")
                            .font(.callout.weight(.medium))
                            .foregroundStyle(.orange)
                    }
                } else {
                    Text("Safe cancel stops cleanly before the next step (never mid-write).")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                Spacer()

                Button(role: .destructive) {
                    appState.cancelActiveLiveSession()
                } label: {
                    Text(session.isCancelling ? "Cancelling…" : "Cancel Safely")
                }
                .buttonStyle(.bordered)
                .disabled(session.isCancelling)

            case .cancelled:
                Button("Try Again") {
                    appState.retryActiveLiveSession()
                }
                .buttonStyle(.bordered)

                Spacer()

                Button("Close") {
                    appState.dismissLiveSessionSheet()
                }
                .buttonStyle(.borderedProminent)
                .keyboardShortcut(.defaultAction)

            case .failed:
                Button("Try Again") {
                    appState.retryActiveLiveSession()
                }
                .buttonStyle(.bordered)

                Button {
                    Task { await appState.launchTerminalFallbackFromSheet() }
                } label: {
                    Label("Use Terminal Instead", systemImage: "terminal")
                }
                .buttonStyle(.borderless)
                .foregroundStyle(.secondary)
                .font(.callout)

                Spacer()

                Button("Close") {
                    appState.dismissLiveSessionSheet()
                }
                .buttonStyle(.borderedProminent)
                .keyboardShortcut(.defaultAction)

            case .finished:
                Spacer()

                Button("Done") {
                    appState.dismissLiveSessionSheet()
                }
                .buttonStyle(.borderedProminent)
                .tint((session.completionReady ?? false) ? .green : .accentColor)
                .controlSize(.large)
                .keyboardShortcut(.defaultAction)
            }
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 14)
        .background(.bar)
    }

    // MARK: - Helpers

    private func labeledBadge(title: String, value: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title)
                .font(.caption2)
                .foregroundStyle(.secondary)
            Text(value)
                .font(.callout.weight(.semibold))
        }
    }

    private func safetyCalloutRow(icon: String, color: Color, text: String) -> some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: icon)
                .font(.callout)
                .foregroundStyle(color)
                .frame(width: 18)
            Text(text)
                .font(.caption)
                .foregroundStyle(.primary)
        }
    }

    private func expressBadgeText(for session: LiveSessionPresentation) -> String {
        if session.action == .expressApply && session.isSinglePassFused {
            return "1-Pass Express Apply (~6s · Zero Cable Replugs)"
        }
        return "Single-Session Express (Zero Cable Replugs)"
    }

    private func actionIcon(for action: LiveCommandAction) -> String {
        switch action {
        case .preflight, .dump: return "magnifyingglass.circle.fill"
        case .apply, .expressApply: return "bolt.shield.fill"
        case .putback, .expressPutback: return "arrow.uturn.backward.circle.fill"
        }
    }

    private func actionAccent(for action: LiveCommandAction) -> Color {
        switch action {
        case .preflight, .dump: return .blue
        case .apply, .expressApply: return .green
        case .putback, .expressPutback: return .orange
        }
    }

    private func phaseColor(_ session: LiveSessionPresentation) -> Color {
        switch session.phase {
        case .confirming, .running: return .blue
        case .finished: return (session.completionReady ?? false) ? .green : .red
        case .cancelled: return session.wasAdminAuthCancelled ? .blue : .orange
        case .failed: return .red
        }
    }

    private func phaseIcon(_ session: LiveSessionPresentation) -> String {
        switch session.phase {
        case .confirming, .running: return "bolt.horizontal.circle.fill"
        case .finished: return (session.completionReady ?? false) ? "checkmark.circle.fill" : "exclamationmark.triangle.fill"
        case .cancelled: return session.wasAdminAuthCancelled ? "info.circle.fill" : "hand.raised.circle.fill"
        case .failed: return "xmark.octagon.fill"
        }
    }

    private func phaseHeadline(_ session: LiveSessionPresentation) -> String {
        switch session.phase {
        case .confirming:
            return "Ready to Authorize"
        case .running:
            return session.isCancelling ? "Cancelling safely before next step…" : "Running \(session.actionTitle)…"
        case .finished:
            return "\(session.actionTitle) Complete"
        case .cancelled:
            return session.wasAdminAuthCancelled ? "Authorization Cancelled" : "Session Cancelled"
        case .failed:
            return "\(session.actionTitle) Failed"
        }
    }

    private func stepStatusColor(_ status: LiveStepStatus) -> Color {
        switch status {
        case .pending: return .secondary
        case .waitingDrive(let first): return first ? .blue : .orange
        case .active: return .blue
        case .done: return .green
        case .failed: return .red
        }
    }

    private func stepRowBackground(_ status: LiveStepStatus) -> Color {
        switch status {
        case .pending: return Color(nsColor: .textBackgroundColor).opacity(0.45)
        case .waitingDrive(let first): return (first ? Color.blue : Color.orange).opacity(0.08)
        case .active: return Color.blue.opacity(0.09)
        case .done: return Color.green.opacity(0.07)
        case .failed: return Color.red.opacity(0.09)
        }
    }

    private func stepRowBorderOpacity(_ status: LiveStepStatus) -> Double {
        switch status {
        case .pending: return 0.14
        case .waitingDrive, .active: return 0.45
        case .done: return 0.30
        case .failed: return 0.45
        }
    }
}
