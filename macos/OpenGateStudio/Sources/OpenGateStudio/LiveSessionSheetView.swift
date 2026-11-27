import OpenGateStudioCore
import SwiftUI

public struct LiveSessionSheetView: View {
    @EnvironmentObject private var appState: AppState
    @State private var pulseActive: Bool = false

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
                .frame(minWidth: 640, idealWidth: 680, minHeight: 520, idealHeight: 620)
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
                .clipShape(RoundedRectangle(cornerRadius: 8))

            VStack(alignment: .leading, spacing: 3) {
                Text("Live USB — \(session.actionTitle)")
                    .font(.headline)
                HStack(spacing: 8) {
                    Text("\(session.cameraDisplayName)")
                        .font(.caption.weight(.semibold))
                    Text("•")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Text("Required FW \(session.requiredFirmware)")
                        .font(.caption.monospaced().weight(.semibold))
                        .foregroundStyle(session.bodyId == "fx3_702" ? .orange : .green)
                }
            }

            Spacer()

            HStack(spacing: 5) {
                Image(systemName: "memorychip")
                Text("Volatile RAM Only")
            }
            .font(.caption.weight(.semibold))
            .padding(.horizontal, 10)
            .padding(.vertical, 5)
            .background(Color.blue.opacity(0.14))
            .foregroundStyle(.blue)
            .clipShape(Capsule())
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 14)
        .background(.bar)
    }

    // MARK: - Confirming Phase

    private func confirmingBody(_ session: LiveSessionPresentation) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                // Summary Card
                VStack(alignment: .leading, spacing: 10) {
                    HStack {
                        Text("Session Plan")
                            .font(.subheadline.weight(.semibold))
                        Spacer()
                        let closingBadge = session.action == .apply
                            ? " + closing Movie verify"
                            : (session.action == .putback ? " + closing stock check" : "")
                        Text("\(session.estimatedStepCount) \(session.estimatedStepCount == 1 ? "step" : "steps")\(closingBadge)")
                            .font(.caption.monospaced().weight(.semibold))
                            .padding(.horizontal, 8)
                            .padding(.vertical, 3)
                            .background(Color.secondary.opacity(0.14))
                            .clipShape(Capsule())
                    }

                    HStack(spacing: 16) {
                        labeledBadge(title: "Camera", value: session.cameraDisplayName)
                        labeledBadge(title: "Exact Firmware", value: session.requiredFirmware)
                        labeledBadge(
                            title: "Mode",
                            value: session.requiresVolatileRamConfirmation ? "Volatile RAM Write" : "Read-Only Inspection"
                        )
                    }

                    if session.action == .apply && !session.selectedPacks.isEmpty {
                        VStack(alignment: .leading, spacing: 5) {
                            Text("Selected Packs")
                                .font(.caption.weight(.semibold))
                                .foregroundStyle(.secondary)
                            ScrollView(.horizontal, showsIndicators: false) {
                                HStack(spacing: 6) {
                                    packPill("core_open_gate", highlight: true)
                                    ForEach(session.selectedPacks.filter { $0 != "core_open_gate" }, id: \.self) { pack in
                                        packPill(pack, highlight: false)
                                    }
                                }
                            }
                        }
                    }

                    if !session.estimatedStepsPreview.isEmpty {
                        VStack(alignment: .leading, spacing: 4) {
                            Text("Planned Step Order")
                                .font(.caption.weight(.semibold))
                                .foregroundStyle(.secondary)
                            Text(session.estimatedStepsPreview.joined(separator: "  →  "))
                                .font(.caption.monospaced())
                                .foregroundStyle(.primary)
                                .textSelection(.enabled)
                        }
                    }
                }
                .padding(14)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(
                    RoundedRectangle(cornerRadius: 10)
                        .fill(Color(nsColor: .controlBackgroundColor))
                )
                .overlay(
                    RoundedRectangle(cornerRadius: 10)
                        .stroke(Color.secondary.opacity(0.20), lineWidth: 1)
                )

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
                            text: "24p (23.98p) / 25p (PAL) / 30p (29.97p) only while Open-Gate is active. Do not switch to 50p / 60p / 120p."
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
                            text: "Read-only preflight inspects camera RAM without writing anything. Connect the camera in Stills mode (Mass Storage) when prompted."
                        )
                    }
                }
                .padding(12)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(Color.blue.opacity(0.06))
                .overlay(
                    RoundedRectangle(cornerRadius: 10)
                        .stroke(Color.blue.opacity(0.22), lineWidth: 1)
                )
                .clipShape(RoundedRectangle(cornerRadius: 10))

                // Clickable Safety Confirmation Switches (NO command typing!)
                VStack(alignment: .leading, spacing: 12) {
                    Text("Confirm Before Authorizing")
                        .font(.subheadline.weight(.semibold))

                    Toggle(isOn: Binding(
                        get: { appState.activeLiveSession?.confirmedFirmwareAndUsb ?? false },
                        set: { appState.activeLiveSession?.confirmedFirmwareAndUsb = $0 }
                    )) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text("I verified my camera menu shows firmware \(session.requiredFirmware) and USB Connection = Mass Storage")
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
                .padding(14)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(
                    RoundedRectangle(cornerRadius: 10)
                        .fill(Color(nsColor: .controlBackgroundColor))
                )
                .overlay(
                    RoundedRectangle(cornerRadius: 10)
                        .stroke(session.canAuthorizeAndStart ? Color.green.opacity(0.45) : Color.orange.opacity(0.35), lineWidth: 1)
                )

                HStack(spacing: 8) {
                    Image(systemName: "touchid")
                        .foregroundStyle(.secondary)
                    Text("Next: macOS will ask for your administrator password or Touch ID once to temporarily release USB Mass Storage so OpenGate Studio can talk directly to the camera.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
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
                if !session.steps.isEmpty {
                    Text("\(session.completedProgressUnits) / \(session.steps.count + (session.includesClosingDump ? 1 : 0)) steps")
                        .font(.caption.monospaced().weight(.semibold))
                        .foregroundStyle(.secondary)
                }
            }

            ProgressView(value: session.progressFraction)
                .progressViewStyle(.linear)
                .tint(phaseColor(session))
        }
        .padding(14)
        .background(
            RoundedRectangle(cornerRadius: 10)
                .fill(Color(nsColor: .controlBackgroundColor))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 10)
                .stroke(phaseColor(session).opacity(0.30), lineWidth: 1)
        )
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
                RoundedRectangle(cornerRadius: 12)
                    .stroke(Color.blue.opacity(0.40), lineWidth: 1.5)
            )
            .clipShape(RoundedRectangle(cornerRadius: 12))

        case .connectInitialDrive(_, let detail, let stepId):
            HStack(alignment: .top, spacing: 14) {
                Image(systemName: "cable.connector")
                    .font(.system(size: 28, weight: .semibold))
                    .foregroundStyle(.white)
                    .frame(width: 46, height: 46)
                    .background(Color.blue)
                    .clipShape(RoundedRectangle(cornerRadius: 10))

                VStack(alignment: .leading, spacing: 4) {
                    HStack {
                        Text("ACTION REQUIRED")
                            .font(.caption2.weight(.bold))
                            .padding(.horizontal, 7)
                            .padding(.vertical, 2)
                            .background(Color.blue.opacity(0.22))
                            .foregroundStyle(.blue)
                            .clipShape(Capsule())
                        if let stepId, !stepId.isEmpty {
                            Text("Step \(stepId)")
                                .font(.caption2.monospaced().weight(.semibold))
                                .foregroundStyle(.secondary)
                        }
                    }
                    Text("Connect USB-C in Stills Mode (Mass Storage)")
                        .font(.title3.weight(.bold))
                        .foregroundStyle(.primary)
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
                RoundedRectangle(cornerRadius: 12)
                    .stroke(Color.blue.opacity(0.75), lineWidth: 2)
            )
            .clipShape(RoundedRectangle(cornerRadius: 12))

        case .replugUsbDrive(_, let detail, let stepId):
            HStack(alignment: .top, spacing: 14) {
                Image(systemName: "arrow.triangle.2.circlepath.circle.fill")
                    .font(.system(size: 30, weight: .semibold))
                    .foregroundStyle(.white)
                    .frame(width: 48, height: 48)
                    .background(Color.orange)
                    .clipShape(RoundedRectangle(cornerRadius: 10))
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

                        Text("KEEP CAMERA ON")
                            .font(.caption2.weight(.heavy))
                            .padding(.horizontal, 8)
                            .padding(.vertical, 2)
                            .background(Color.red.opacity(0.18))
                            .foregroundStyle(.red)
                            .clipShape(Capsule())

                        if let stepId, !stepId.isEmpty {
                            Text("Next: \(stepId)")
                                .font(.caption2.monospaced().weight(.semibold))
                                .foregroundStyle(.secondary)
                        }
                    }

                    Text("Unplug USB-C and Plug Right Back In — Keep Camera ON!")
                        .font(.title3.weight(.bold))
                        .foregroundStyle(.primary)
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
                RoundedRectangle(cornerRadius: 12)
                    .stroke(Color.orange.opacity(pulseActive ? 0.95 : 0.55), lineWidth: 2.5)
            )
            .clipShape(RoundedRectangle(cornerRadius: 12))

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
                    .clipShape(RoundedRectangle(cornerRadius: 10))
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

                        Text("24p / 25p / 30p ONLY")
                            .font(.caption2.weight(.bold))
                            .padding(.horizontal, 8)
                            .padding(.vertical, 2)
                            .background(Color.blue.opacity(0.18))
                            .foregroundStyle(.blue)
                            .clipShape(Capsule())
                    }

                    Text("Unplug USB-C → Switch Camera to MOVIE Mode (24p/25p/30p) → Replug USB-C")
                        .font(.title3.weight(.bold))
                        .foregroundStyle(.primary)
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
                RoundedRectangle(cornerRadius: 12)
                    .stroke(Color.purple.opacity(pulseActive ? 0.90 : 0.50), lineWidth: 2.5)
            )
            .clipShape(RoundedRectangle(cornerRadius: 12))
        }
    }

    @ViewBuilder
    private func finishedOutcomeBanner(_ session: LiveSessionPresentation) -> some View {
        let isReady = session.completionReady ?? false
        let isPositive = isReady
        let accent: Color = isPositive ? .green : .red

        let headline: String = {
            switch session.action {
            case .apply:
                return isReady
                    ? "Open Gate Applied — Ready to Shoot (24p / 25p / 30p)!"
                    : "Apply Completed — Verification Needs Review"
            case .preflight, .dump:
                return isReady
                    ? "Read-Only Preflight Passed — VERDICT READY"
                    : "Preflight Blocked — Camera Not Ready"
            case .putback:
                return isReady
                    ? "Camera Restored & Verified Stock RAM"
                    : "Put Back Completed — Stock Verification Unconfirmed"
            }
        }()

        let subtitle: String = {
            switch session.action {
            case .apply:
                return isReady
                    ? "Keep the camera ON while shooting 24p / 25p / 30p open-gate clips. Pull battery >= 10s anytime to return to stock."
                    : (session.completionVerdict ?? "Check the closing verification dump verdict before recording.")
            case .preflight, .dump:
                return isReady
                    ? "Gate 3 (Apply Selected Packs) is now unlocked in Tab 2."
                    : "Pull the battery for >= 10 seconds to clear residual RAM state, then run Read-Only Preflight again."
            case .putback:
                return isReady
                    ? "Volatile RAM patches were reversed and verified back to stock state."
                    : "Closing stock verification did not pass. Pull battery >= 10s to guarantee clean stock RAM."
            }
        }()

        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 10) {
                Image(systemName: isPositive ? "checkmark.seal.fill" : "exclamationmark.triangle.fill")
                    .font(.title2)
                    .foregroundStyle(accent)
                VStack(alignment: .leading, spacing: 2) {
                    Text(headline)
                        .font(.headline)
                        .foregroundStyle(accent)
                    Text(subtitle)
                        .font(.callout)
                        .foregroundStyle(.primary)
                }
                Spacer()
            }

            if let verdict = session.completionVerdict, !verdict.isEmpty {
                Text("Verdict: \(verdict)\(session.completionSessionId.map { "  •  Session: \($0)" } ?? "")")
                    .font(.caption.monospaced())
                    .foregroundStyle(.secondary)
            }

            if !session.completionActivePacks.isEmpty {
                Text("Active Packs: \(session.completionActivePacks.joined(separator: ", "))")
                    .font(.caption.monospaced())
                    .foregroundStyle(.secondary)
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(accent.opacity(0.11))
        .overlay(
            RoundedRectangle(cornerRadius: 10)
                .stroke(accent.opacity(0.45), lineWidth: 1.5)
        )
        .clipShape(RoundedRectangle(cornerRadius: 10))
    }

    private func cancelledOutcomeBanner(_ session: LiveSessionPresentation) -> some View {
        let color: Color = session.wasAdminAuthCancelled ? .blue : .orange
        let icon: String = session.wasAdminAuthCancelled ? "info.circle.fill" : "hand.raised.circle.fill"
        let title: String = session.wasAdminAuthCancelled
            ? "Administrator authorization cancelled — nothing was sent to the camera"
            : "Session Cancelled Safely"

        return HStack(alignment: .top, spacing: 12) {
            Image(systemName: icon)
                .font(.title2)
                .foregroundStyle(color)
            VStack(alignment: .leading, spacing: 3) {
                Text(title)
                    .font(.headline)
                if !session.wasAdminAuthCancelled, let msg = session.cancelMessage, !msg.isEmpty {
                    Text(msg)
                        .font(.callout)
                        .foregroundStyle(.secondary)
                } else {
                    Text("You can click Try Again to re-authorize, or Close to return to Apply & Packs.")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                }
            }
            Spacer()
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(color.opacity(0.10))
        .overlay(
            RoundedRectangle(cornerRadius: 10)
                .stroke(color.opacity(0.38), lineWidth: 1)
        )
        .clipShape(RoundedRectangle(cornerRadius: 10))
    }

    private func failedOutcomeBanner(_ session: LiveSessionPresentation) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .top, spacing: 10) {
                Image(systemName: "xmark.octagon.fill")
                    .font(.title2)
                    .foregroundStyle(.red)
                VStack(alignment: .leading, spacing: 3) {
                    Text("\(session.actionTitle) Stopped With an Error")
                        .font(.headline)
                        .foregroundStyle(.red)
                    Text(session.failureMessage ?? "An unexpected error occurred. Expand Live Output Log for details.")
                        .font(.callout)
                        .textSelection(.enabled)
                }
                Spacer()
            }

            if session.leftBehindWarning {
                HStack(alignment: .top, spacing: 8) {
                    Image(systemName: "battery.25")
                        .foregroundStyle(.orange)
                    Text("Some volatile RAM steps may still be active. Pull the camera battery for >= 10 seconds to restore clean stock RAM before retrying.")
                        .font(.caption.weight(.medium))
                }
                .padding(10)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(Color.orange.opacity(0.14))
                .clipShape(RoundedRectangle(cornerRadius: 8))
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.red.opacity(0.10))
        .overlay(
            RoundedRectangle(cornerRadius: 10)
                .stroke(Color.red.opacity(0.45), lineWidth: 1.5)
        )
        .clipShape(RoundedRectangle(cornerRadius: 10))
    }

    // MARK: - Live Step Cards

    private func stepsListCard(_ session: LiveSessionPresentation) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Step Progress")
                .font(.subheadline.weight(.semibold))

            if session.steps.isEmpty && !session.includesClosingDump {
                HStack(spacing: 8) {
                    if session.phase == .running {
                        ProgressView().controlSize(.small)
                        Text("Preparing step plan...")
                            .font(.callout)
                            .foregroundStyle(.secondary)
                    } else {
                        Text("No steps were executed.")
                            .font(.callout)
                            .foregroundStyle(.secondary)
                    }
                }
                .padding(.vertical, 6)
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
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 10)
                .fill(Color(nsColor: .controlBackgroundColor))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 10)
                .stroke(Color.secondary.opacity(0.18), lineWidth: 1)
        )
    }

    private func stepRow(code: String, indexLabel: String, summary: String, status: LiveStepStatus) -> some View {
        let rowAccent = stepStatusColor(status)
        return HStack(spacing: 10) {
            Text(indexLabel)
                .font(.caption2.monospaced().weight(.bold))
                .foregroundStyle(.secondary)
                .frame(width: 20, alignment: .trailing)

            Text(code)
                .font(.caption.monospaced().weight(.bold))
                .padding(.horizontal, 8)
                .padding(.vertical, 3)
                .background(rowAccent.opacity(0.16))
                .foregroundStyle(rowAccent)
                .clipShape(RoundedRectangle(cornerRadius: 5))

            Text(summary)
                .font(.callout)
                .lineLimit(2)

            Spacer()

            stepStatusAccessory(status)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 8)
        .background(
            RoundedRectangle(cornerRadius: 8)
                .fill(stepRowBackground(status))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 8)
                .stroke(rowAccent.opacity(stepRowBorderOpacity(status)), lineWidth: 1)
        )
    }

    @ViewBuilder
    private func stepStatusAccessory(_ status: LiveStepStatus) -> some View {
        switch status {
        case .pending:
            HStack(spacing: 4) {
                Image(systemName: "circle")
                Text("Pending")
            }
            .font(.caption)
            .foregroundStyle(.secondary)

        case .waitingDrive(let first):
            HStack(spacing: 5) {
                Image(systemName: first ? "cable.connector" : "arrow.triangle.2.circlepath")
                Text(first ? "Connect USB" : "Replug USB")
            }
            .font(.caption.weight(.semibold))
            .foregroundStyle(first ? .blue : .orange)

        case .active:
            HStack(spacing: 6) {
                ProgressView().controlSize(.small)
                Text("Running...")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.blue)
            }

        case .done(let outcome):
            HStack(spacing: 5) {
                Image(systemName: "checkmark.circle.fill")
                    .foregroundStyle(.green)
                Text(outcome)
                    .font(.caption.monospaced().weight(.semibold))
                    .foregroundStyle(.green)
            }

        case .failed(let msg):
            HStack(spacing: 5) {
                Image(systemName: "xmark.circle.fill")
                    .foregroundStyle(.red)
                Text(msg ?? "Failed")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.red)
                    .lineLimit(1)
            }
        }
    }

    // MARK: - Live Output Log Disclosure

    private func liveLogDisclosure(_ session: LiveSessionPresentation) -> some View {
        DisclosureGroup(
            isExpanded: Binding(
                get: { appState.activeLiveSession?.isLogExpanded ?? false },
                set: { appState.activeLiveSession?.isLogExpanded = $0 }
            )
        ) {
            ScrollView {
                Text(session.logText.isEmpty ? "Waiting for live output..." : session.logText)
                    .font(.caption.monospaced())
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .textSelection(.enabled)
                    .padding(10)
            }
            .frame(minHeight: 110, maxHeight: 190)
            .background(Color(nsColor: .textBackgroundColor))
            .clipShape(RoundedRectangle(cornerRadius: 8))
            .padding(.top, 6)
        } label: {
            HStack {
                Label("Live Output Log", systemImage: "text.alignleft")
                    .font(.subheadline.weight(.semibold))
                Spacer()
                let lineCount = session.logText.isEmpty ? 0 : session.logText.split(whereSeparator: \.isNewline).count
                Text("\(lineCount) lines")
                    .font(.caption2.monospaced())
                    .foregroundStyle(.secondary)
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

    // MARK: - Footer

    private func sheetFooter(_ session: LiveSessionPresentation) -> some View {
        HStack(spacing: 10) {
            switch session.phase {
            case .confirming:
                Button("Cancel") {
                    appState.dismissLiveSessionSheet()
                }
                .keyboardShortcut(.cancelAction)

                Button {
                    Task { await appState.launchTerminalFallbackFromSheet() }
                } label: {
                    Label("Use Terminal Instead", systemImage: "terminal")
                }
                .buttonStyle(.borderless)
                .foregroundStyle(.secondary)
                .font(.callout)

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
                        Text("Cancelling safely before next step...")
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
                    Text(session.isCancelling ? "Cancelling..." : "Cancel Safely")
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

    private func packPill(_ packId: String, highlight: Bool) -> some View {
        Text(packId)
            .font(.caption2.monospaced().weight(.semibold))
            .padding(.horizontal, 8)
            .padding(.vertical, 3)
            .background(highlight ? Color.blue.opacity(0.16) : Color.secondary.opacity(0.14))
            .foregroundStyle(highlight ? .blue : .primary)
            .clipShape(Capsule())
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

    private func actionIcon(for action: LiveCommandAction) -> String {
        switch action {
        case .preflight, .dump: return "magnifyingglass.circle.fill"
        case .apply: return "bolt.shield.fill"
        case .putback: return "arrow.uturn.backward.circle.fill"
        }
    }

    private func actionAccent(for action: LiveCommandAction) -> Color {
        switch action {
        case .preflight, .dump: return .blue
        case .apply: return .green
        case .putback: return .orange
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
            return session.isCancelling ? "Cancelling safely before next step..." : "Running \(session.actionTitle)..."
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
