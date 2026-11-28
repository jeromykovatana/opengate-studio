import OpenGateStudioCore
import SwiftUI

public struct LiveSessionSheetView: View {
    @EnvironmentObject private var appState: AppState
    @State private var pulseActive: Bool = false
    @State private var showConfirmAdvanced: Bool = false
    @State private var sudoPassword: String = ""
    @State private var isSudoCached: Bool = false

    public init() {}

    public var body: some View {
        Group {
            if let session = appState.activeLiveSession {
                HStack(spacing: 0) {
                    timelineRail(session)
                        .frame(width: 224)
                        .background(.bar)

                    Divider()

                    detailPane(session)
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                        .background(Color(nsColor: .controlBackgroundColor))
                }
                .frame(minWidth: 680, idealWidth: 720, minHeight: 460, idealHeight: 540)
                .interactiveDismissDisabled(session.phase == .running)
                .onAppear {
                    withAnimation(.easeInOut(duration: 0.95).repeatForever(autoreverses: true)) {
                        pulseActive = true
                    }
                    refreshSudoCacheStatus()
                }
                .onChange(of: session.phase) { _, newPhase in
                    if newPhase == .confirming {
                        refreshSudoCacheStatus()
                    }
                }
                .onDisappear {
                    sudoPassword = ""
                }
            } else {
                EmptyView()
            }
        }
    }

    // MARK: - Left Timeline Rail

    private enum RailNodeState {
        case done
        case active
        case failed
        case idle
    }

    private func timelineRail(_ session: LiveSessionPresentation) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            VStack(alignment: .leading, spacing: 10) {
                HStack(spacing: 9) {
                    Image(systemName: actionIcon(for: session.action))
                        .font(.callout.weight(.semibold))
                        .foregroundStyle(actionAccent(for: session.action))
                        .frame(width: 28, height: 28)
                        .background(actionAccent(for: session.action).opacity(0.14))
                        .clipShape(RoundedRectangle(cornerRadius: 7, style: .continuous))

                    VStack(alignment: .leading, spacing: 1) {
                        Text(session.cameraDisplayName)
                            .font(.callout.weight(.semibold))
                            .lineLimit(1)
                        Text("FW \(session.requiredFirmware) · \(railModeSummary(session))")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                    }
                }

                if session.phase != .confirming {
                    VStack(alignment: .leading, spacing: 5) {
                        ProgressView(value: session.progressFraction)
                            .progressViewStyle(.linear)
                            .tint(phaseColor(session))
                        Text(phaseHeadline(session))
                            .font(.caption)
                            .foregroundStyle(session.phase == .failed ? .red : .secondary)
                            .lineLimit(2)
                    }
                }
            }
            .padding(16)

            Divider()

            ScrollView(.vertical, showsIndicators: false) {
                VStack(alignment: .leading, spacing: 0) {
                    timelineItems(for: session)
                }
                .padding(16)
            }

            Divider()

            railFooter(session)
                .padding(14)
        }
    }

    @ViewBuilder
    private func timelineItems(for session: LiveSessionPresentation) -> some View {
        let authDone = session.phase != .confirming && !session.wasAdminAuthCancelled
        let authState: RailNodeState = {
            if session.phase == .confirming { return .active }
            if session.wasAdminAuthCancelled { return .failed }
            return .done
        }()

        if session.phase == .confirming {
            if session.isExpressAction {
                timelineNode(index: "1", title: "Authorize", subtitle: nil, state: .active, isLast: false)
                timelineNode(
                    index: "2",
                    title: session.action == .expressPutback ? "Restore Stock" : "Patch RAM",
                    subtitle: session.estimatedStepsPreview.first,
                    state: .idle,
                    isLast: false
                )
                timelineNode(index: "3", title: "Verify & Unplug", subtitle: nil, state: .idle, isLast: true)
            } else {
                let preview = session.estimatedStepsPreview
                let showEachStep = !preview.isEmpty && preview.count <= 4
                let finalTitle: String = {
                    switch session.action {
                    case .apply: return "Verify & Unplug"
                    case .putback: return "Stock Check"
                    case .preflight, .dump: return "Verify RAM"
                    case .expressApply, .expressPutback: return "Verify & Unplug"
                    }
                }()

                timelineNode(index: "1", title: "Authorize", subtitle: nil, state: .active, isLast: false)

                if showEachStep {
                    ForEach(Array(preview.enumerated()), id: \.offset) { idx, stepCode in
                        timelineNode(
                            index: "\(idx + 2)",
                            title: stepCode,
                            subtitle: nil,
                            state: .idle,
                            isLast: false
                        )
                    }
                    timelineNode(
                        index: "\(preview.count + 2)",
                        title: finalTitle,
                        subtitle: nil,
                        state: .idle,
                        isLast: true
                    )
                } else {
                    let stepCount = max(session.estimatedStepCount, 1)
                    timelineNode(
                        index: "2",
                        title: "Run \(stepCount) steps",
                        subtitle: nil,
                        state: .idle,
                        isLast: false
                    )
                    timelineNode(index: "3", title: finalTitle, subtitle: nil, state: .idle, isLast: true)
                }
            }
        } else {
            let hasClosing = session.includesClosingDump
            let hasSteps = !session.steps.isEmpty

            timelineNode(
                index: "1",
                title: authDone ? "Authorized" : "Authorize",
                subtitle: nil,
                state: authState,
                isLast: !hasSteps && !hasClosing && session.phase != .running
            )

            if !hasSteps && !hasClosing {
                if session.phase == .running {
                    timelineNode(
                        index: "2",
                        title: "Preparing step plan…",
                        subtitle: nil,
                        state: .active,
                        isLast: true
                    )
                } else {
                    timelineNode(
                        index: "2",
                        title: "No steps executed",
                        subtitle: nil,
                        state: session.phase == .failed ? .failed : .idle,
                        isLast: true
                    )
                }
            } else {
                ForEach(Array(session.steps.enumerated()), id: \.element.id) { idx, step in
                    timelineNode(
                        index: "\(idx + 2)",
                        title: step.summary,
                        subtitle: step.id,
                        state: mapStepStatus(step.status),
                        isLast: !hasClosing && idx == session.steps.count - 1
                    )
                }

                if hasClosing {
                    let isStockCheck = session.closingKind == "stock_check" || session.action == .putback || session.action == .expressPutback
                    timelineNode(
                        index: "\(session.steps.count + 2)",
                        title: isStockCheck ? "Stock Check" : "Verify & Unplug",
                        subtitle: isStockCheck ? "CHECK" : "VERIFY",
                        state: mapStepStatus(session.closingDumpStatus ?? .pending),
                        isLast: true
                    )
                }
            }
        }
    }

    private func timelineNode(
        index: String,
        title: String,
        subtitle: String?,
        state: RailNodeState,
        isLast: Bool
    ) -> some View {
        HStack(alignment: .top, spacing: 10) {
            VStack(spacing: 2) {
                ZStack {
                    switch state {
                    case .done:
                        Circle()
                            .fill(Color.green)
                            .frame(width: 18, height: 18)
                        Image(systemName: "checkmark")
                            .font(.system(size: 9, weight: .bold))
                            .foregroundStyle(.white)
                    case .active:
                        Circle()
                            .fill(Color.blue)
                            .frame(width: 18, height: 18)
                        Text(index)
                            .font(.caption2.weight(.bold).monospacedDigit())
                            .foregroundStyle(.white)
                    case .failed:
                        Circle()
                            .fill(Color.red)
                            .frame(width: 18, height: 18)
                        Image(systemName: "xmark")
                            .font(.system(size: 9, weight: .bold))
                            .foregroundStyle(.white)
                    case .idle:
                        Circle()
                            .strokeBorder(Color.primary.opacity(0.22), lineWidth: 1.5)
                            .background(Circle().fill(Color(nsColor: .controlBackgroundColor)))
                            .frame(width: 18, height: 18)
                        Text(index)
                            .font(.caption2.weight(.semibold).monospacedDigit())
                            .foregroundStyle(.secondary)
                    }
                }

                if !isLast {
                    Rectangle()
                        .fill(state == .done ? Color.green : Color.primary.opacity(0.14))
                        .frame(width: 1.5, height: 22)
                }
            }

            VStack(alignment: .leading, spacing: 1) {
                Text(title)
                    .font(.caption.weight(state == .active ? .semibold : .medium))
                    .foregroundStyle(state == .active ? .primary : .secondary)
                    .lineLimit(2)

                if let subtitle, !subtitle.isEmpty {
                    Text(subtitle)
                        .font(.caption2.monospaced())
                        .foregroundStyle(.tertiary)
                }
            }
            .padding(.top, 1)
            .padding(.bottom, isLast ? 0 : 8)
        }
    }

    @ViewBuilder
    private func railFooter(_ session: LiveSessionPresentation) -> some View {
        switch session.phase {
        case .confirming:
            Button {
                sudoPassword = ""
                appState.dismissLiveSessionSheet()
            } label: {
                Text("Cancel")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.bordered)
            .keyboardShortcut(.cancelAction)

        case .running:
            VStack(spacing: 6) {
                Button(role: .destructive) {
                    appState.cancelActiveLiveSession()
                } label: {
                    Text(session.isCancelling ? "Cancelling…" : "Cancel Safely")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.bordered)
                .disabled(session.isCancelling)

                Text(
                    session.isCancelling
                        ? "Stopping cleanly before next step…"
                        : "Stops safely before next step."
                )
                .font(.caption2)
                .foregroundStyle(session.isCancelling ? .orange : .secondary)
                .multilineTextAlignment(.center)
            }

        case .cancelled, .failed:
            VStack(spacing: 8) {
                Button {
                    appState.retryActiveLiveSession()
                } label: {
                    Text("Try Again")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.bordered)

                Button {
                    appState.dismissLiveSessionSheet()
                } label: {
                    Text("Close")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .keyboardShortcut(.defaultAction)
            }

        case .finished:
            Button {
                appState.dismissLiveSessionSheet()
            } label: {
                Text("Done")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .tint((session.completionReady ?? false) ? .green : .accentColor)
            .keyboardShortcut(.defaultAction)
        }
    }

    // MARK: - Right Active Detail Pane

    @ViewBuilder
    private func detailPane(_ session: LiveSessionPresentation) -> some View {
        if session.phase == .confirming {
            confirmingDetailPane(session)
        } else {
            executionDetailPane(session)
        }
    }

    private func confirmingDetailPane(_ session: LiveSessionPresentation) -> some View {
        let missingPassword = !isSudoCached && !appState.useSystemAuthDialog && sudoPassword.isEmpty

        return ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                HStack(alignment: .center, spacing: 8) {
                    Text("Authorize \(session.actionTitle)")
                        .font(.title3.weight(.semibold))
                    Spacer()
                    StudioStatusPill(
                        session.requiresVolatileRamConfirmation ? "Volatile RAM" : "Read-Only",
                        color: session.requiresVolatileRamConfirmation ? .blue : .green
                    )
                }

                if (session.action == .apply || session.action == .expressApply) && !session.selectedPacks.isEmpty {
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: 6) {
                            StudioStatusPill(appState.humanReadablePackTitle(for: "core_open_gate"), color: .blue)
                            ForEach(session.selectedPacks.filter { $0 != "core_open_gate" }, id: \.self) { pack in
                                StudioStatusPill(appState.humanReadablePackTitle(for: pack), color: .secondary)
                            }
                        }
                    }
                }

                VStack(alignment: .leading, spacing: 6) {
                    if session.requiresVolatileRamConfirmation {
                        Text("Writes volatile RAM only (zero eMMC or SD writes; battery pull >= 10s restores stock). Keep the camera ON between prompts.")
                            .font(.callout)
                            .foregroundStyle(.secondary)
                        Text(
                            (session.bodyId == "a7c_203" || session.bodyId == "zve10_203")
                                ? "Shoot XAVC S 4K 24p (23.98p) 100M while active (1.185x vertical de-squeeze unless True 3840x2560 Raster is enabled)."
                                : "Shoot 24p, 25p, or 30p only while Open-Gate is active (do not switch to 50p, 60p, or 120p)."
                        )
                        .font(.caption)
                        .foregroundStyle(.secondary)

                        if session.bodyId == "fx3_702" {
                            Text("FX3: Verify Model Name is ILME-FX3 (not ILME-FX3A). Do not retry Playback if Unable to Display appears.")
                                .font(.caption.weight(.medium))
                                .foregroundStyle(.red)
                        }
                    } else {
                        Text("Read-only inspection checks camera RAM without writing anything. Connect the camera in Stills mode (Mass Storage) when prompted.")
                            .font(.callout)
                            .foregroundStyle(.secondary)
                    }
                }

                if session.isExpressAction {
                    Toggle(
                        "I understand volatile RAM & 24p/25p/30p rules (connect in Stills / Mass Storage)",
                        isOn: Binding(
                            get: { appState.activeLiveSession?.confirmedVolatileRam ?? false },
                            set: { newValue in
                                appState.activeLiveSession?.confirmedVolatileRam = newValue
                                appState.activeLiveSession?.confirmedFirmwareAndUsb = newValue
                            }
                        )
                    )
                    .font(.callout)
                } else {
                    VStack(alignment: .leading, spacing: 8) {
                        Toggle(
                            "I verified camera firmware \(session.requiredFirmware) and USB Connection = Mass Storage",
                            isOn: Binding(
                                get: { appState.activeLiveSession?.confirmedFirmwareAndUsb ?? false },
                                set: { appState.activeLiveSession?.confirmedFirmwareAndUsb = $0 }
                            )
                        )
                        .font(.callout)

                        if session.requiresVolatileRamConfirmation {
                            Toggle(
                                "I understand this writes volatile RAM only (keep camera ON; battery pull >= 10s restores stock)",
                                isOn: Binding(
                                    get: { appState.activeLiveSession?.confirmedVolatileRam ?? false },
                                    set: { appState.activeLiveSession?.confirmedVolatileRam = $0 }
                                )
                            )
                            .font(.callout)
                        }
                    }
                }

                Divider()

                inlineAdminAuthSection(session)

                Button {
                    startSessionFromSheet()
                } label: {
                    Label("Authorize & Start", systemImage: "lock.open.fill")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .tint(actionAccent(for: session.action))
                .controlSize(.large)
                .disabled(!session.canAuthorizeAndStart || missingPassword)

                HStack(alignment: .top) {
                    DisclosureGroup("Planned Steps (\(session.estimatedStepsPreview.count))", isExpanded: $showConfirmAdvanced) {
                        if !session.estimatedStepsPreview.isEmpty {
                            Text(session.estimatedStepsPreview.joined(separator: "  →  "))
                                .font(.caption.monospaced())
                                .foregroundStyle(.secondary)
                                .textSelection(.enabled)
                                .padding(.top, 4)
                        }
                    }
                    .font(.caption.weight(.medium))
                    .foregroundStyle(.secondary)

                    Spacer()

                    Button("Terminal Fallback") {
                        Task { await appState.launchTerminalFallbackFromSheet() }
                    }
                    .buttonStyle(.borderless)
                    .font(.caption.weight(.medium))
                    .foregroundStyle(.secondary)
                }
            }
            .padding(20)
        }
    }

    @ViewBuilder
    private func inlineAdminAuthSection(_ session: LiveSessionPresentation) -> some View {
        if isSudoCached {
            HStack(spacing: 8) {
                Image(systemName: "checkmark.shield.fill")
                    .foregroundStyle(.green)
                Text("Administrator session active (no password prompt needed)")
                    .font(.callout.weight(.medium))
                    .foregroundStyle(.green)
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 8)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color.green.opacity(0.10))
            .overlay(
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .strokeBorder(Color.green.opacity(0.30), lineWidth: 1)
            )
            .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        } else {
            VStack(alignment: .leading, spacing: 8) {
                Picker("Authorization Method", selection: $appState.useSystemAuthDialog) {
                    Text("sudo Password").tag(false)
                    Text("Touch ID").tag(true)
                }
                .pickerStyle(.segmented)
                .labelsHidden()

                if !appState.useSystemAuthDialog {
                    SecureField("Enter your Mac login password", text: $sudoPassword)
                        .textFieldStyle(.roundedBorder)
                        .onSubmit {
                            if session.canAuthorizeAndStart && !sudoPassword.isEmpty {
                                startSessionFromSheet()
                            }
                        }
                    Text("Caches administrator session for ~5 min · never saved or logged.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                } else {
                    HStack(spacing: 8) {
                        Image(systemName: "touchid")
                            .foregroundStyle(.secondary)
                        Text("macOS will show the Touch ID / password prompt. If macOS 26/27 blocks USB access, switch to sudo Password.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            }
        }
    }

    private func executionDetailPane(_ session: LiveSessionPresentation) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            if session.phase == .running, let banner = session.activeBanner {
                actionBannerView(banner)
            } else if session.phase == .finished {
                finishedOutcomeBanner(session)
            } else if session.phase == .cancelled {
                cancelledOutcomeBanner(session)
            } else if session.phase == .failed {
                failedOutcomeBanner(session)
            }

            liveOutputPanel(session)
        }
        .padding(20)
    }

    private func liveOutputPanel(_ session: LiveSessionPresentation) -> some View {
        let lineCount = session.logText.isEmpty ? 0 : session.logText.split(whereSeparator: \.isNewline).count

        return VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text("Live Output")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                Spacer()
                Text("\(lineCount) lines")
                    .font(.caption2.monospacedDigit())
                    .foregroundStyle(.secondary)
            }

            ScrollView {
                Text(session.logText.isEmpty ? "Waiting for live output…" : session.logText)
                    .font(.caption.monospaced())
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .textSelection(.enabled)
                    .padding(10)
            }
            .frame(minHeight: 150, maxHeight: .infinity)
            .background(Color(nsColor: .textBackgroundColor))
            .overlay(
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .strokeBorder(Color.primary.opacity(0.10), lineWidth: 1)
            )
            .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        }
    }

    // MARK: - Action & Outcome Banners

    @ViewBuilder
    private func actionBannerView(_ banner: LiveActionBanner) -> some View {
        switch banner {
        case .awaitingAdminAuth:
            HStack(alignment: .center, spacing: 12) {
                Image(systemName: "lock.shield.fill")
                    .font(.title3)
                    .foregroundStyle(.blue)
                VStack(alignment: .leading, spacing: 2) {
                    Text("Waiting for Administrator Authorization")
                        .font(.callout.weight(.semibold))
                    Text("Approve the native macOS Touch ID or password prompt to start.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                ProgressView().controlSize(.small)
            }
            .padding(12)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color.blue.opacity(0.09))
            .overlay(
                RoundedRectangle(cornerRadius: 9, style: .continuous)
                    .stroke(Color.blue.opacity(0.35), lineWidth: 1)
            )
            .clipShape(RoundedRectangle(cornerRadius: 9, style: .continuous))

        case .connectInitialDrive(_, let detail, let stepId):
            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 6) {
                    Text("Connect USB-C in Stills Mode (Mass Storage)")
                        .font(.callout.weight(.semibold))
                        .foregroundStyle(.blue)
                    Spacer()
                    if let stepId, !stepId.isEmpty {
                        Text(stepId)
                            .font(.caption2.monospaced())
                            .foregroundStyle(.secondary)
                    }
                }
                Text(detail)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            .padding(12)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color.blue.opacity(0.09))
            .overlay(
                RoundedRectangle(cornerRadius: 9, style: .continuous)
                    .stroke(Color.blue.opacity(0.40), lineWidth: 1)
            )
            .clipShape(RoundedRectangle(cornerRadius: 9, style: .continuous))

        case .replugUsbDrive(_, let detail, let stepId):
            HStack(alignment: .top, spacing: 11) {
                Image(systemName: "arrow.triangle.2.circlepath.circle.fill")
                    .font(.title2)
                    .foregroundStyle(.orange)
                    .scaleEffect(pulseActive ? 1.06 : 0.96)

                VStack(alignment: .leading, spacing: 4) {
                    HStack(spacing: 6) {
                        StudioStatusPill("UNPLUG & REPLUG USB-C", color: .orange)
                        StudioStatusPill("KEEP CAMERA ON", color: .red)
                        if let stepId, !stepId.isEmpty {
                            Text(stepId)
                                .font(.caption2.monospaced())
                                .foregroundStyle(.secondary)
                        }
                    }
                    Text("Unplug USB-C and Plug Right Back In — Keep Camera ON!")
                        .font(.callout.weight(.semibold))
                    Text(detail)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer()
            }
            .padding(12)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color.orange.opacity(pulseActive ? 0.18 : 0.10))
            .overlay(
                RoundedRectangle(cornerRadius: 9, style: .continuous)
                    .stroke(Color.orange.opacity(pulseActive ? 0.85 : 0.45), lineWidth: 1.5)
            )
            .clipShape(RoundedRectangle(cornerRadius: 9, style: .continuous))

        case .switchToMovieMode(_, let detail, let hint):
            HStack(alignment: .top, spacing: 11) {
                Image(systemName: "video.fill")
                    .font(.title2)
                    .foregroundStyle(.purple)
                    .scaleEffect(pulseActive ? 1.06 : 0.96)

                VStack(alignment: .leading, spacing: 4) {
                    HStack(spacing: 6) {
                        StudioStatusPill("SWITCH TO MOVIE MODE", color: .purple)
                        StudioStatusPill("24p / 25p / 30p ONLY", color: .blue)
                    }
                    Text("Unplug USB-C → Switch Camera to MOVIE Mode (24p/25p/30p) → Replug USB-C")
                        .font(.callout.weight(.semibold))
                    Text(detail)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    if let hint, !hint.isEmpty {
                        Text("Camera control: \(hint)")
                            .font(.caption.weight(.medium))
                            .foregroundStyle(.purple)
                    }
                }
                Spacer()
            }
            .padding(12)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color.purple.opacity(pulseActive ? 0.16 : 0.09))
            .overlay(
                RoundedRectangle(cornerRadius: 9, style: .continuous)
                    .stroke(Color.purple.opacity(pulseActive ? 0.75 : 0.40), lineWidth: 1.5)
            )
            .clipShape(RoundedRectangle(cornerRadius: 9, style: .continuous))
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

        let showSafeToUnplug: Bool = isReady && (
            session.action == .expressApply
            || session.action == .apply
            || session.action == .expressPutback
            || session.action == .putback
        )

        StudioSurface(accent: accent, padding: 13) {
            VStack(alignment: .leading, spacing: 9) {
                if showSafeToUnplug {
                    safeToUnplugHeader(isPutback: session.action == .expressPutback || session.action == .putback)
                }

                HStack(spacing: 10) {
                    Image(systemName: isReady ? "checkmark.seal.fill" : "exclamationmark.triangle.fill")
                        .font(.title3)
                        .foregroundStyle(accent)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(headline)
                            .font(.callout.weight(.semibold))
                            .foregroundStyle(accent)
                        Text(subtitle)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                }

                if showSafeToUnplug {
                    safeToUnplugStepsBox(isPutback: session.action == .expressPutback || session.action == .putback)
                }

                if isReady && session.action == .expressApply && session.bodyId == "a7s3_501" {
                    Text("Tip: On a7S III, if Movie live view looks purple on first switch, tap Record start/stop once.")
                        .font(.caption.weight(.medium))
                        .foregroundStyle(.purple)
                }

                if let verdict = session.completionVerdict, !verdict.isEmpty {
                    Text("Verdict: \(verdict)\(session.completionSessionId.map { "  ·  Session: \($0)" } ?? "")")
                        .font(.caption2.monospaced())
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
        VStack(alignment: .leading, spacing: 8) {
            StudioCallout(
                icon: "xmark.octagon.fill",
                color: .red,
                title: "\(session.actionTitle) Stopped With an Error",
                detail: session.failureMessage ?? "An unexpected error occurred. Check Live Output below for details."
            )

            if session.leftBehindWarning {
                StudioCallout(
                    icon: "battery.25",
                    color: .orange,
                    title: "Volatile RAM May Still Contain Partial Steps",
                    detail: "Pull the camera battery for >= 10 seconds to restore clean stock RAM before retrying."
                )
            }

            Button {
                Task { await appState.launchTerminalFallbackFromSheet() }
            } label: {
                Label("Use Terminal Instead", systemImage: "terminal")
            }
            .buttonStyle(.borderless)
            .font(.caption.weight(.medium))
            .foregroundStyle(.secondary)
        }
    }

    private func safeToUnplugHeader(isPutback: Bool) -> some View {
        HStack(spacing: 8) {
            Image(systemName: "cable.connector")
                .font(.caption.weight(.bold))
            Text("SAFE TO UNPLUG USB-C")
                .font(.caption.weight(.heavy))
                .tracking(0.6)
            Spacer()
            Text(isPutback ? "Stock RAM Verified" : "3:2 Open-Gate Ready")
                .font(.caption2.weight(.bold))
                .padding(.horizontal, 8)
                .padding(.vertical, 2)
                .background(Color.white.opacity(0.22))
                .clipShape(Capsule())
        }
        .foregroundStyle(.white)
        .padding(.horizontal, 10)
        .padding(.vertical, 6)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.green)
        .clipShape(RoundedRectangle(cornerRadius: 7, style: .continuous))
    }

    @ViewBuilder
    private func safeToUnplugStepsBox(isPutback: Bool) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            if isPutback {
                Text("Camera RAM is 100% stock — safe to unplug USB-C")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.primary)
            } else {
                Text("1. Unplug USB-C cable now")
                    .font(.caption.weight(.semibold))
                Text("2. Switch camera to Movie (24p / 25p / 30p only)")
                    .font(.caption.weight(.semibold))
                Text("3. Keep Power Save = Off while shooting")
                    .font(.caption.weight(.semibold))
            }
        }
        .padding(9)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.green.opacity(0.10))
        .overlay(
            RoundedRectangle(cornerRadius: 7, style: .continuous)
                .strokeBorder(Color.green.opacity(0.32), lineWidth: 1)
        )
        .clipShape(RoundedRectangle(cornerRadius: 7, style: .continuous))
    }

    // MARK: - Helpers

    private func refreshSudoCacheStatus() {
        Task {
            let cached: Bool = await Task.detached(priority: .userInitiated) {
                StudioBridge.canRunPasswordlessSudo()
            }.value
            isSudoCached = cached
        }
    }

    private func startSessionFromSheet() {
        let passwordToPass: String?
        if isSudoCached || appState.useSystemAuthDialog {
            passwordToPass = nil
        } else {
            passwordToPass = sudoPassword
        }
        sudoPassword = ""
        Task {
            await appState.authorizeAndStartLiveSession(adminPassword: passwordToPass)
        }
    }

    private func railModeSummary(_ session: LiveSessionPresentation) -> String {
        if session.isExpressAction {
            return session.isSinglePassFused ? "1-Pass Express" : "Express"
        }
        return session.requiresVolatileRamConfirmation ? "Step-by-Step" : "Read-Only"
    }

    private func mapStepStatus(_ status: LiveStepStatus) -> RailNodeState {
        switch status {
        case .pending: return .idle
        case .waitingDrive, .active: return .active
        case .done: return .done
        case .failed: return .failed
        }
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

    private func phaseHeadline(_ session: LiveSessionPresentation) -> String {
        switch session.phase {
        case .confirming:
            return "Ready to Authorize"
        case .running:
            return session.isCancelling
                ? "Cancelling safely before next step…"
                : "Running · Step \(min(session.completedProgressUnits + 1, max(session.totalProgressUnits, 1))) of \(session.totalProgressUnits)"
        case .finished:
            return "\(session.actionTitle) Complete"
        case .cancelled:
            return session.wasAdminAuthCancelled ? "Authorization Cancelled" : "Session Cancelled"
        case .failed:
            return "\(session.actionTitle) Failed"
        }
    }
}
