import AppKit
import OpenGateStudioCore
import SwiftUI

public struct DiagnosticsSheetView: View {
    @EnvironmentObject private var appState: AppState
    @Environment(\.dismiss) private var dismiss

    public init() {}

    public var body: some View {
        VStack(spacing: 0) {
            sheetHeader
            Divider()

            Group {
                switch appState.selectedDiagnosticsTab {
                case .console:
                    consoleTab
                case .pins:
                    pinsTab
                case .fieldReport:
                    fieldReportTab
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .frame(minWidth: 660, idealWidth: 740, minHeight: 520, idealHeight: 620)
    }

    // MARK: - Header

    private var sheetHeader: some View {
        HStack(spacing: 12) {
            Text("Diagnostics & Field Tools")
                .font(.headline)

            Spacer()

            Picker("Section", selection: $appState.selectedDiagnosticsTab) {
                ForEach(DiagnosticsTab.allCases) { tab in
                    Text(tab.rawValue).tag(tab)
                }
            }
            .pickerStyle(.segmented)
            .frame(width: 310)

            Spacer()

            Button("Done") {
                dismiss()
            }
            .buttonStyle(.borderedProminent)
            .keyboardShortcut(.defaultAction)
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 14)
        .background(.bar)
    }

    // MARK: - Tab 1: Console Log

    private var consoleTab: some View {
        VStack(spacing: 0) {
            HStack {
                Text("\(appState.consoleLogs.count) recorded command(s)")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Spacer()
                if !appState.consoleLogs.isEmpty {
                    Button("Clear Log") {
                        appState.consoleLogs.removeAll()
                    }
                    .buttonStyle(.bordered)
                    .controlSize(.small)
                }
            }
            .padding(.horizontal, 20)
            .padding(.vertical, 10)

            Divider()

            if appState.consoleLogs.isEmpty {
                ContentUnavailableView(
                    "No CLI Activity Yet",
                    systemImage: "terminal",
                    description: Text("Camera checks, pin verification, and clip diagnostics will appear here.")
                )
            } else {
                ScrollView {
                    VStack(alignment: .leading, spacing: 10) {
                        ForEach(appState.consoleLogs) { trace in
                            StudioSurface(padding: 12) {
                                VStack(alignment: .leading, spacing: 6) {
                                    HStack {
                                        Text("$ \(trace.command)")
                                            .font(.caption.monospaced().weight(.semibold))
                                            .textSelection(.enabled)
                                        Spacer()
                                        StudioStatusPill(
                                            "exit \(trace.exitCode)",
                                            color: trace.exitCode == 0 ? .green : .red
                                        )
                                    }

                                    let trimmedOut = trace.stdout.trimmingCharacters(in: .whitespacesAndNewlines)
                                    if !trimmedOut.isEmpty {
                                        Text(trimmedOut)
                                            .font(.caption2.monospaced())
                                            .foregroundStyle(.secondary)
                                            .textSelection(.enabled)
                                    }

                                    let trimmedErr = trace.stderr.trimmingCharacters(in: .whitespacesAndNewlines)
                                    if !trimmedErr.isEmpty {
                                        Text("stderr: \(trimmedErr)")
                                            .font(.caption2.monospaced())
                                            .foregroundStyle(.red)
                                            .textSelection(.enabled)
                                    }
                                }
                            }
                        }
                    }
                    .padding(20)
                }
            }
        }
    }

    // MARK: - Tab 2: Kit Integrity (SHA-256 Pins)

    private var pinsTab: some View {
        let verified = appState.pinsVerifiedForAllOrSelected

        return ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                StudioSurface(accent: verified ? .green : .orange, padding: 16) {
                    HStack(spacing: 12) {
                        Image(systemName: verified ? "checkmark.shield.fill" : "exclamationmark.shield.fill")
                            .font(.title2)
                            .foregroundStyle(verified ? .green : .orange)

                        VStack(alignment: .leading, spacing: 2) {
                            Text(verified ? "All Kit Manifests & Helpers Verified" : "Kit Verification Needed or Mismatch")
                                .font(.headline)
                            if let pinRes = appState.pinResult {
                                Text("\(pinRes.checkedFiles) signed kit files checked against SHA-256 manifest pins.")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            } else {
                                Text("Run verification to confirm every helper binary matches its signed SHA-256 digest.")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                        }

                        Spacer()

                        Button {
                            Task { await appState.verifyPins() }
                        } label: {
                            if appState.isVerifyingPins {
                                ProgressView().controlSize(.small)
                            } else {
                                Text("Re-Verify Pins")
                            }
                        }
                        .buttonStyle(.borderedProminent)
                        .disabled(appState.isVerifyingPins)
                    }
                }

                if let pinRes = appState.pinResult {
                    StudioSurface(padding: 14) {
                        VStack(alignment: .leading, spacing: 10) {
                            Text("Per-Camera Kit Status")
                                .font(.subheadline.weight(.semibold))

                            ForEach(pinRes.bodies.keys.sorted(), id: \.self) { bodyId in
                                Divider()
                                let entry = pinRes.bodies[bodyId]
                                let displayName = appState.bodies.first(where: { $0.bodyId == bodyId })?.displayName ?? bodyId
                                let ok = entry?.ok ?? false

                                VStack(alignment: .leading, spacing: 4) {
                                    HStack {
                                        Image(systemName: ok ? "checkmark.circle.fill" : "xmark.circle.fill")
                                            .foregroundStyle(ok ? .green : .red)
                                        Text(displayName)
                                            .font(.callout.weight(.medium))
                                        Text("(\(bodyId))")
                                            .font(.caption.monospaced())
                                            .foregroundStyle(.secondary)
                                        Spacer()
                                        if let count = entry?.checkedFiles {
                                            Text("\(count) files")
                                                .font(.caption.monospacedDigit())
                                                .foregroundStyle(.secondary)
                                        }
                                    }

                                    if let issues = entry?.issues, !issues.isEmpty {
                                        ForEach(issues, id: \.self) { issue in
                                            Text("• \(issue)")
                                                .font(.caption)
                                                .foregroundStyle(.red)
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
            .padding(20)
        }
    }

    // MARK: - Tab 3: Field Test Report Builder

    private var fieldReportTab: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                StudioCallout(
                    icon: "doc.text.magnifyingglass",
                    color: .blue,
                    title: "Field Test & Reliability Report Bundle",
                    detail: "Generates FIELD_REPORT.md + JSON from your test clips and session history without copying raw camera dumps."
                )

                StudioSurface(padding: 14) {
                    VStack(alignment: .leading, spacing: 12) {
                        HStack(spacing: 10) {
                            Button {
                                chooseReportFolder()
                            } label: {
                                Label("Select Test Clips Folder…", systemImage: "folder.badge.plus")
                            }
                            .buttonStyle(.bordered)

                            if let folder = appState.reportClipsFolderURL {
                                Text(folder.path)
                                    .font(.caption.monospaced())
                                    .lineLimit(1)
                                    .truncationMode(.middle)
                                    .foregroundStyle(.secondary)
                            } else {
                                Text("Optional: choose folder of MP4/XML clips & screenshots")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                        }

                        LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 10) {
                            TextField("Media Card (e.g., Sony CEA-G 160GB)", text: $appState.reportMediaCard)
                            TextField("Lens (e.g., Sony 24mm f/1.4 GM)", text: $appState.reportLens)
                            TextField("Ambient Temp °C (e.g., 23C)", text: $appState.reportAmbientC)
                            TextField("Soak Duration Mins (e.g., 45)", text: $appState.reportSoakMinutes)
                            TextField("Thermal Result (e.g., No warning)", text: $appState.reportThermalResult)
                            TextField("Re-Activation Secs (e.g., 58s)", text: $appState.reportReactivationSeconds)
                        }
                        .textFieldStyle(.roundedBorder)
                        .font(.callout)

                        TextField("AF + De-Squeeze / HDMI Notes", text: $appState.reportAfDesqueezeNotes)
                            .textFieldStyle(.roundedBorder)
                            .font(.callout)

                        TextField("General Observations / Resolve & Gyroflow Notes", text: $appState.reportNotes)
                            .textFieldStyle(.roundedBorder)
                            .font(.callout)

                        HStack(spacing: 10) {
                            Button {
                                Task { await appState.buildFieldTestReport() }
                            } label: {
                                HStack(spacing: 6) {
                                    if appState.isBuildingReport {
                                        ProgressView().controlSize(.small)
                                    } else {
                                        Image(systemName: "doc.badge.gearshape")
                                    }
                                    Text("Generate Report Bundle")
                                }
                            }
                            .buttonStyle(.borderedProminent)
                            .disabled(appState.isBuildingReport)

                            if appState.reportResult != nil {
                                Button {
                                    appState.copyReportMarkdownToClipboard()
                                } label: {
                                    Label(
                                        appState.copiedReportConfirmation ? "Copied Markdown!" : "Copy Markdown",
                                        systemImage: appState.copiedReportConfirmation ? "checkmark.circle.fill" : "doc.on.doc"
                                    )
                                }
                                .buttonStyle(.bordered)

                                Button {
                                    appState.revealReportFolderInFinder()
                                } label: {
                                    Label("Reveal in Finder", systemImage: "folder")
                                }
                                .buttonStyle(.bordered)
                            }
                        }

                        if let reportErr = appState.reportError {
                            Text(reportErr)
                                .font(.caption)
                                .foregroundStyle(.red)
                        }

                        if let rep = appState.reportResult {
                            StudioCallout(
                                icon: "checkmark.seal.fill",
                                color: .green,
                                title: "Report Ready: \(rep.clipsScanned) clips scanned (\(rep.clipsPassed) passed, \(rep.clipsFailed) failed)",
                                detail: rep.markdownPath
                            )
                        }
                    }
                }
            }
            .padding(20)
        }
    }

    private func chooseReportFolder() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        panel.message = "Select folder containing test MP4/XML clips, LCD photos, and screenshots"
        if panel.runModal() == .OK, let url = panel.url {
            appState.reportClipsFolderURL = url
        }
    }
}
