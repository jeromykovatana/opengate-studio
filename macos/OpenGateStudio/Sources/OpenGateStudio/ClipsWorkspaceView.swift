import AppKit
import OpenGateStudioCore
import SwiftUI
import UniformTypeIdentifiers

public struct ClipsWorkspaceView: View {
    @EnvironmentObject private var appState: AppState
    @State private var isDropTargeted: Bool = false
    @State private var copiedCropConfirmation: Bool = false

    public init() {}

    public var body: some View {
        VStack(spacing: 0) {
            workspaceActionBar
            Divider()
            workspaceBody
        }
        .onDrop(of: [.fileURL], isTargeted: $isDropTargeted) { providers in
            handleDrop(providers: providers)
        }
        .overlay {
            if isDropTargeted {
                RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .strokeBorder(Color.accentColor, style: StrokeStyle(lineWidth: 2, dash: [8, 5]))
                    .background(Color.accentColor.opacity(0.06))
                    .padding(10)
                    .allowsHitTesting(false)
            }
        }
        .inspector(isPresented: $appState.isClipInspectorPresented) {
            ClipInspectorPanel()
                .inspectorColumnWidth(min: 280, ideal: 320, max: 390)
        }
    }

    // MARK: - Top Action Strip

    private var workspaceActionBar: some View {
        HStack(spacing: 12) {
            Button {
                chooseClipOrCard()
            } label: {
                Label("Open Clip or Card…", systemImage: "folder")
            }
            .buttonStyle(.bordered)
            .controlSize(.small)

            if let sourceSummary = loadedSourceSummary {
                HStack(spacing: 6) {
                    Image(systemName: appState.ingestResult != nil ? "sdcard.fill" : "film")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Text(sourceSummary)
                        .font(.caption.weight(.medium))
                        .lineLimit(1)
                        .truncationMode(.middle)
                    Button {
                        appState.clearClipsWorkspace()
                    } label: {
                        Image(systemName: "xmark.circle.fill")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    .buttonStyle(.borderless)
                    .help("Clear loaded clip or card")
                }
            }

            Spacer()

            Button {
                appState.showGyroflowPresetsSheet = true
            } label: {
                Label("Gyroflow Presets…", systemImage: "gyroscope")
            }
            .buttonStyle(.bordered)
            .controlSize(.small)

            let queuedCount = queuedProxyCount
            Button {
                appState.showProxyExportSheet = true
            } label: {
                Label(
                    queuedCount > 0 ? "Export Proxies (\(queuedCount))…" : "Export Proxies…",
                    systemImage: "square.and.arrow.up"
                )
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.small)
            .disabled(queuedCount == 0)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
        .background(.bar)
    }

    private var loadedSourceSummary: String? {
        if let root = appState.ingestRootURL {
            return root.lastPathComponent
        }
        if let mp4 = appState.selectedMP4URL {
            return mp4.lastPathComponent
        }
        return nil
    }

    private var queuedProxyCount: Int {
        if appState.ingestResult != nil {
            return appState.selectedProxyClipPaths.count
        }
        return appState.selectedMP4URL != nil ? 1 : 0
    }

    // MARK: - Main Workspace Body

    @ViewBuilder
    private var workspaceBody: some View {
        if appState.ingestResult != nil || appState.isIngestingBatch || appState.ingestError != nil {
            batchSplitWorkspace
        } else if appState.selectedMP4URL != nil || appState.isCheckingClip || appState.clipError != nil {
            ScrollView {
                singleOrSelectedClipCanvas
                    .frame(maxWidth: 820)
                    .frame(maxWidth: .infinity)
                    .padding(22)
            }
        } else {
            emptyDropzoneState
        }
    }

    private var emptyDropzoneState: some View {
        VStack {
            Spacer()
            StudioSurface(padding: 32) {
                VStack(spacing: 16) {
                    Image(systemName: "film.stack")
                        .font(.system(size: 40, weight: .light))
                        .foregroundStyle(Color.accentColor)

                    VStack(spacing: 6) {
                        Text("Inspect & Prepare Open-Gate Clips")
                            .font(.title3.weight(.semibold))
                        Text("Drop a Sony .MP4 clip or an SD card folder (PRIVATE/M4ROOT/CLIP) to verify 3:2 dimensions, M01.XML metadata, Gyroflow readiness, and delivery framing.")
                            .font(.callout)
                            .foregroundStyle(.secondary)
                            .multilineTextAlignment(.center)
                            .frame(maxWidth: 460)
                    }

                    HStack(spacing: 12) {
                        Button {
                            chooseClipOrCard()
                        } label: {
                            Label("Open Clip or SD Card…", systemImage: "folder.badge.plus")
                        }
                        .buttonStyle(.borderedProminent)
                        .controlSize(.large)

                        Button {
                            appState.showGyroflowPresetsSheet = true
                        } label: {
                            Label("Gyroflow 3:2 Presets…", systemImage: "gyroscope")
                        }
                        .buttonStyle(.bordered)
                        .controlSize(.large)
                    }
                }
                .frame(maxWidth: .infinity)
            }
            .frame(maxWidth: 580)
            .padding(24)
            Spacer()
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    // MARK: - Batch SD-Card Sidebar + Center Canvas

    private var batchSplitWorkspace: some View {
        HStack(spacing: 0) {
            batchClipListSidebar
                .frame(width: 285)
            Divider()
            ScrollView {
                singleOrSelectedClipCanvas
                    .frame(maxWidth: 780)
                    .frame(maxWidth: .infinity)
                    .padding(20)
            }
        }
    }

    private var batchClipListSidebar: some View {
        VStack(spacing: 0) {
            VStack(alignment: .leading, spacing: 10) {
                if let batch = appState.ingestResult {
                    HStack(spacing: 6) {
                        StudioStatusPill("\(batch.clipsScanned) clips", color: .blue)
                        StudioStatusPill("\(batch.clipsPassed) ok", color: .green)
                        if batch.clipsFailed > 0 {
                            StudioStatusPill("\(batch.clipsFailed) issue", color: .red)
                        }
                        Spacer()
                    }
                }

                HStack(spacing: 8) {
                    Picker("Expect", selection: $appState.ingestExpectMode) {
                        Text("Auto").tag("auto")
                        Text("3:2").tag("open-gate")
                        Text("16:9").tag("stock")
                    }
                    .pickerStyle(.segmented)
                    .controlSize(.small)
                    .onChange(of: appState.ingestExpectMode) { _, _ in
                        Task { await appState.runBatchIngest() }
                    }

                    Menu {
                        Toggle("Scan Subfolders", isOn: $appState.ingestRecursive)
                        Divider()
                        Button("Select Passed Clips for Proxy") {
                            if let clips = appState.ingestResult?.clips {
                                appState.selectedProxyClipPaths = Set(clips.filter(\.ok).map(\.file))
                            }
                        }
                        Button("Select All Clips for Proxy") {
                            if let clips = appState.ingestResult?.clips {
                                appState.selectedProxyClipPaths = Set(clips.map(\.file))
                            }
                        }
                        Button("Clear Proxy Selection") {
                            appState.selectedProxyClipPaths.removeAll()
                        }
                        Divider()
                        Button("Rescan Card") {
                            Task { await appState.runBatchIngest() }
                        }
                    } label: {
                        Image(systemName: "line.3.horizontal.decrease.circle")
                            .font(.callout)
                    }
                    .menuStyle(.borderlessButton)
                    .frame(width: 24)
                    .help("Batch Scan & Proxy Selection Options")
                }
            }
            .padding(12)
            .background(.bar)

            Divider()

            if appState.isIngestingBatch {
                VStack(spacing: 10) {
                    Spacer()
                    ProgressView()
                    Text("Scanning card clips & gyro metadata…")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Spacer()
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if let batch = appState.ingestResult {
                if batch.clips.isEmpty {
                    ContentUnavailableView(
                        "No Clips Found",
                        systemImage: "film",
                        description: Text("No .MP4 clips were found in this folder.")
                    )
                } else {
                    List(batch.clips) { clip in
                        batchSidebarRow(clip)
                    }
                    .listStyle(.sidebar)
                }
            } else if let err = appState.ingestError {
                VStack(spacing: 8) {
                    Spacer()
                    StudioCallout(
                        icon: "exclamationmark.triangle.fill",
                        color: .red,
                        title: "Card Scan Failed",
                        detail: err
                    )
                    .padding(12)
                    Spacer()
                }
            }
        }
    }

    private func batchSidebarRow(_ clip: IngestedClipItem) -> some View {
        let isSelected = appState.activeInspectedBatchClip?.id == clip.id
        let isQueued = appState.selectedProxyClipPaths.contains(clip.file)

        return HStack(spacing: 8) {
            Toggle("", isOn: Binding(
                get: { isQueued },
                set: { enabled in
                    if enabled {
                        appState.selectedProxyClipPaths.insert(clip.file)
                    } else {
                        appState.selectedProxyClipPaths.remove(clip.file)
                    }
                }
            ))
            .labelsHidden()
            .toggleStyle(.checkbox)
            .controlSize(.small)

            Circle()
                .fill(clip.ok ? Color.green : Color.red)
                .frame(width: 7, height: 7)

            VStack(alignment: .leading, spacing: 2) {
                Text(clip.filename)
                    .font(.callout.weight(isSelected ? .semibold : .regular))
                    .lineLimit(1)
                Text("\(clip.width)×\(clip.height) · \(clip.fps) · \(clip.codec)")
                    .font(.caption2.monospacedDigit())
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }

            Spacer()

            if clip.readyForGyroflow {
                Image(systemName: "gyroscope")
                    .font(.caption)
                    .foregroundStyle(.teal)
                    .help("Gyroflow Ready")
            }
        }
        .padding(.vertical, 4)
        .padding(.horizontal, 6)
        .background(
            RoundedRectangle(cornerRadius: 6, style: .continuous)
                .fill(isSelected ? Color.accentColor.opacity(0.14) : Color.clear)
        )
        .contentShape(Rectangle())
        .onTapGesture {
            appState.selectBatchClip(clip)
        }
    }

    // MARK: - Center Verdict & 3:2 Framing Canvas

    private var singleOrSelectedClipCanvas: some View {
        VStack(alignment: .leading, spacing: 18) {
            if let err = appState.clipError {
                StudioCallout(
                    icon: "exclamationmark.triangle.fill",
                    color: .red,
                    title: "Could Not Inspect Clip",
                    detail: err
                )
            }

            if appState.isCheckingClip {
                StudioSurface(padding: 16) {
                    HStack(spacing: 10) {
                        ProgressView().controlSize(.small)
                        Text("Inspecting clip dimensions, sidecar XML, and gyro track…")
                            .font(.callout)
                            .foregroundStyle(.secondary)
                    }
                }
            } else if let verdict = currentVerdictSummary {
                verdictBannerCard(verdict)
            }

            framingPreviewCard
        }
    }

    private struct ClipVerdictSummary {
        let ok: Bool
        let title: String
        let specsLine: String
        let issues: [String]
        let warnings: [String]
    }

    private var currentVerdictSummary: ClipVerdictSummary? {
        if let res = appState.clipResult {
            let dur = res.durationSec.map { String(format: "%.1fs", $0) }
            let mbps = res.avgBitrateMbps.map { String(format: "%.0f Mbps", $0) }
            let prof = res.codecProfileLevel ?? res.codec
            let parts = ["\(res.width)×\(res.height) (\(res.displayAspect))", res.fps, prof, dur, mbps].compactMap { $0 }
            let title = res.ok
                ? (appState.clipExpectMode == "stock" ? "Stock Baseline Clip Verified" : "Native 3:2 Open-Gate Clip Ready")
                : "Clip Needs Attention"
            return ClipVerdictSummary(
                ok: res.ok,
                title: title,
                specsLine: parts.joined(separator: "  ·  "),
                issues: res.issues,
                warnings: res.warnings ?? []
            )
        }

        if let clip = appState.activeInspectedBatchClip {
            let dur = clip.durationSec.map { String(format: "%.1fs", $0) }
            let mbps = clip.avgBitrateMbps.map { String(format: "%.0f Mbps", $0) }
            let prof = clip.codecProfileLevel ?? clip.codec
            let parts = ["\(clip.width)×\(clip.height) (\(clip.displayAspect))", clip.fps, prof, dur, mbps].compactMap { $0 }
            let title = clip.ok
                ? (clip.expectedMode == "stock" ? "Stock Baseline Clip Verified" : "Native 3:2 Open-Gate Clip Ready")
                : "Clip Needs Attention"
            return ClipVerdictSummary(
                ok: clip.ok,
                title: title,
                specsLine: parts.joined(separator: "  ·  "),
                issues: clip.issues,
                warnings: clip.warnings
            )
        }

        return nil
    }

    private func verdictBannerCard(_ verdict: ClipVerdictSummary) -> some View {
        StudioSurface(accent: verdict.ok ? .green : .red, padding: 16) {
            VStack(alignment: .leading, spacing: 10) {
                HStack(spacing: 12) {
                    Image(systemName: verdict.ok ? "checkmark.seal.fill" : "exclamationmark.triangle.fill")
                        .font(.title2)
                        .foregroundStyle(verdict.ok ? .green : .red)

                    VStack(alignment: .leading, spacing: 3) {
                        Text(verdict.title)
                            .font(.headline)
                        Text(verdict.specsLine)
                            .font(.caption.monospacedDigit())
                            .foregroundStyle(.secondary)
                    }

                    Spacer()

                    if !appState.isClipInspectorPresented {
                        Button("Details") {
                            appState.isClipInspectorPresented = true
                        }
                        .buttonStyle(.bordered)
                        .controlSize(.small)
                    }
                }

                if !verdict.issues.isEmpty {
                    Divider()
                    ForEach(verdict.issues, id: \.self) { issue in
                        Label(issue, systemImage: "xmark.circle")
                            .font(.callout)
                            .foregroundStyle(.red)
                    }
                }

                if !verdict.warnings.isEmpty {
                    ForEach(verdict.warnings, id: \.self) { warning in
                        Label(warning, systemImage: "info.circle")
                            .font(.caption)
                            .foregroundStyle(.orange)
                    }
                }
            }
        }
    }

    private var activePreviewDimensions: (width: Int, height: Int, label: String) {
        if let res = appState.clipResult, res.width >= 2, res.height >= 2 {
            let name = appState.selectedMP4URL?.lastPathComponent ?? "Selected Clip"
            return (res.width, res.height, name)
        }
        if let clip = appState.activeInspectedBatchClip, clip.width >= 2, clip.height >= 2 {
            return (clip.width, clip.height, clip.filename)
        }
        return (3840, 2560, "Default 3:2 Open-Gate")
    }

    private var framingPreviewCard: some View {
        let dims = activePreviewDimensions
        let specs = DeliveryCropCalculator.compute(width: dims.width, height: dims.height)
        let activeSpec = specs.first(where: { $0.aspect == appState.previewAspect.rawValue }) ?? specs.first

        return StudioSurface(padding: 18) {
            VStack(alignment: .leading, spacing: 14) {
                HStack {
                    Label("Delivery Framing Preview", systemImage: "viewfinder")
                        .font(.headline)
                    Spacer()
                    Text("\(dims.label) · \(dims.width)×\(dims.height)")
                        .font(.caption.monospacedDigit())
                        .foregroundStyle(.secondary)
                }

                DeliveryFramingCanvas(
                    sourceWidth: dims.width,
                    sourceHeight: dims.height,
                    spec: activeSpec,
                    showActionSafe: appState.previewShowActionSafe,
                    showTitleSafe: appState.previewShowTitleSafe
                )
                .frame(height: 300)

                HStack(spacing: 12) {
                    Picker("Delivery Aspect", selection: $appState.previewAspect) {
                        ForEach(DeliveryAspect.allCases) { aspect in
                            Text(aspect.rawValue).tag(aspect)
                        }
                    }
                    .pickerStyle(.segmented)
                    .frame(width: 260)

                    Toggle("Action Safe", isOn: $appState.previewShowActionSafe)
                        .toggleStyle(.checkbox)
                        .controlSize(.small)

                    Toggle("Title Safe", isOn: $appState.previewShowTitleSafe)
                        .toggleStyle(.checkbox)
                        .controlSize(.small)

                    Spacer()

                    if let activeSpec {
                        HStack(spacing: 8) {
                            Text("\(activeSpec.width)×\(activeSpec.height) centered")
                                .font(.caption.monospacedDigit())
                                .foregroundStyle(.secondary)

                            Button {
                                NSPasteboard.general.clearContents()
                                NSPasteboard.general.setString(activeSpec.ffmpegCrop, forType: .string)
                                copiedCropConfirmation = true
                            } label: {
                                Label(
                                    copiedCropConfirmation ? "Copied" : "Copy Crop",
                                    systemImage: copiedCropConfirmation ? "checkmark" : "doc.on.doc"
                                )
                            }
                            .buttonStyle(.bordered)
                            .controlSize(.small)
                            .help("Copy ffmpeg crop filter (\(activeSpec.ffmpegCrop))")
                        }
                    }
                }
            }
        }
        .onChange(of: appState.previewAspect) { _, _ in
            copiedCropConfirmation = false
        }
    }

    // MARK: - Pickers & Drag/Drop

    private func chooseClipOrCard() {
        let panel = NSOpenPanel()
        panel.canChooseFiles = true
        panel.canChooseDirectories = true
        panel.allowsMultipleSelection = false
        panel.allowedContentTypes = [
            .mpeg4Movie,
            .movie,
            .folder,
            UTType(filenameExtension: "mp4") ?? .mpeg4Movie,
        ]
        panel.message = "Select a Sony XAVC .MP4 clip or an SD card folder (PRIVATE/M4ROOT/CLIP)"
        if panel.runModal() == .OK, let url = panel.url {
            Task { await appState.openClipsFromURLs([url]) }
        }
    }

    private func handleDrop(providers: [NSItemProvider]) -> Bool {
        guard let provider = providers.first(where: { $0.hasItemConformingToTypeIdentifier(UTType.fileURL.identifier) }) else {
            return false
        }
        provider.loadItem(forTypeIdentifier: UTType.fileURL.identifier, options: nil) { item, _ in
            let droppedURL: URL?
            if let data = item as? Data {
                droppedURL = URL(dataRepresentation: data, relativeTo: nil)
            } else if let url = item as? URL {
                droppedURL = url
            } else {
                droppedURL = nil
            }
            guard let url = droppedURL else { return }
            Task { @MainActor in
                await appState.openClipsFromURLs([url])
            }
        }
        return true
    }
}
