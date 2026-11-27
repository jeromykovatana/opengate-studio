import AppKit
import OpenGateStudioCore
import SwiftUI

public struct CreatorWorkflowView: View {
    @EnvironmentObject private var appState: AppState

    public init() {}

    public var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                batchIngestCard
                framingPreviewCard
                proxyExportCard
                gyroflowPresetsCard
            }
            .padding(20)
        }
        .task {
            if appState.gyroPresetList == nil && !appState.isLoadingGyroPresets {
                await appState.loadGyroflowPresets()
            }
        }
    }

    // MARK: - 1. Batch SD-Card Ingest

    private var batchIngestCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Label("1. Batch SD-Card Ingest (PRIVATE/M4ROOT/CLIP)", systemImage: "sdcard.fill")
                    .font(.headline)
                Spacer()
                Text("Pairs *M01.XML + runs clip & gyro diagnostics")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            HStack(spacing: 10) {
                Button {
                    chooseIngestFolder()
                } label: {
                    Label("Select Card / Clips Folder...", systemImage: "folder")
                }
                .buttonStyle(.bordered)

                Picker("Expect", selection: $appState.ingestExpectMode) {
                    Text("Auto").tag("auto")
                    Text("Open Gate 3:2").tag("open-gate")
                    Text("Stock 16:9").tag("stock")
                }
                .pickerStyle(.segmented)
                .frame(width: 260)

                Toggle("Recursive", isOn: $appState.ingestRecursive)
                    .toggleStyle(.checkbox)

                Spacer()

                Button {
                    Task { await appState.runBatchIngest() }
                } label: {
                    HStack(spacing: 6) {
                        if appState.isIngestingBatch {
                            ProgressView().controlSize(.small)
                        } else {
                            Image(systemName: "magnifyingglass")
                        }
                        Text("Scan Batch")
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(appState.ingestRootURL == nil || appState.isIngestingBatch)
            }

            if let root = appState.ingestRootURL {
                Text("Folder: \(root.path)")
                    .font(.caption.monospaced())
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .truncationMode(.middle)
            }

            if let err = appState.ingestError {
                Label(err, systemImage: "exclamationmark.triangle.fill")
                    .font(.callout)
                    .foregroundStyle(.red)
            }

            if let batch = appState.ingestResult {
                HStack(spacing: 10) {
                    summaryPill(title: "Scanned", value: "\(batch.clipsScanned)", color: .blue)
                    summaryPill(title: "Passed", value: "\(batch.clipsPassed)", color: .green)
                    summaryPill(title: "Failed", value: "\(batch.clipsFailed)", color: batch.clipsFailed > 0 ? .red : .secondary)
                    summaryPill(title: "Gyroflow Ready", value: "\(batch.gyroflowReadyCount)", color: .teal)
                    Spacer()
                }

                if batch.clips.isEmpty {
                    Text("No .MP4 clips found in this directory.")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                } else {
                    VStack(spacing: 6) {
                        ForEach(batch.clips) { clip in
                            ingestedClipRow(clip)
                        }
                    }
                }
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 10).fill(Color(nsColor: .controlBackgroundColor)))
        .overlay(RoundedRectangle(cornerRadius: 10).stroke(Color.secondary.opacity(0.20), lineWidth: 1))
    }

    private func ingestedClipRow(_ clip: IngestedClipItem) -> some View {
        let isSelected = appState.selectedIngestedClipId == clip.id
        let isChecked = appState.selectedProxyClipPaths.contains(clip.file)

        return HStack(spacing: 10) {
            Toggle("", isOn: Binding(
                get: { isChecked },
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

            Image(systemName: clip.ok ? "checkmark.circle.fill" : "xmark.circle.fill")
                .foregroundStyle(clip.ok ? .green : .red)

            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 6) {
                    Text(clip.filename)
                        .font(.callout.weight(.semibold))
                    Text("\(clip.width)x\(clip.height) (\(clip.displayAspect))")
                        .font(.caption.monospaced())
                        .foregroundStyle(.secondary)
                    Text("• \(clip.fps) • \(clip.codec)")
                        .font(.caption.monospaced())
                        .foregroundStyle(.secondary)
                }
                Text(clip.relativePath)
                    .font(.caption2.monospaced())
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .truncationMode(.middle)
                if !clip.issues.isEmpty {
                    Text(clip.issues.joined(separator: "; "))
                        .font(.caption2)
                        .foregroundStyle(.red)
                        .lineLimit(1)
                }
            }

            Spacer()

            HStack(spacing: 6) {
                miniBadge(label: "XML", ok: clip.xml3x2 == true)
                miniBadge(label: "rtmd \(clip.rtmdSamples)", ok: clip.rtmdGyroPresent && clip.rtmdSamples > 0)
                miniBadge(label: "Gyroflow", ok: clip.readyForGyroflow)
            }

            Button("Preview") {
                appState.selectedIngestedClipId = clip.id
            }
            .buttonStyle(.bordered)
            .controlSize(.small)

            Button("Inspect") {
                Task {
                    appState.selectedTab = .clipInspector
                    await appState.selectMP4File(URL(fileURLWithPath: clip.file))
                }
            }
            .buttonStyle(.bordered)
            .controlSize(.small)
        }
        .padding(8)
        .background(
            RoundedRectangle(cornerRadius: 8)
                .fill(isSelected ? Color.accentColor.opacity(0.10) : Color(nsColor: .windowBackgroundColor))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 8)
                .stroke(isSelected ? Color.accentColor : Color.secondary.opacity(0.15), lineWidth: 1)
        )
    }

    // MARK: - 2. Interactive 3:2 Framing & Delivery Safe-Area Preview

    private var framingPreviewCard: some View {
        let dims = activePreviewDimensions
        let specs = DeliveryCropCalculator.compute(width: dims.width, height: dims.height)
        let activeSpec = specs.first(where: { $0.aspect == appState.previewAspect.rawValue }) ?? specs.first

        return VStack(alignment: .leading, spacing: 12) {
            HStack {
                Label("2. Interactive 3:2 Framing & Delivery Safe-Area Preview", systemImage: "viewfinder")
                    .font(.headline)
                Spacer()
                Text("Source: \(dims.width)x\(dims.height) (\(dims.label))")
                    .font(.caption.monospaced())
                    .foregroundStyle(.secondary)
            }

            HStack(spacing: 12) {
                Picker("Delivery Aspect", selection: $appState.previewAspect) {
                    ForEach(DeliveryAspect.allCases) { aspect in
                        Text(aspect.rawValue).tag(aspect)
                    }
                }
                .pickerStyle(.segmented)
                .frame(width: 280)

                Toggle("90% Action Safe", isOn: $appState.previewShowActionSafe)
                    .toggleStyle(.checkbox)

                Toggle("80% Title Safe", isOn: $appState.previewShowTitleSafe)
                    .toggleStyle(.checkbox)

                Spacer()
            }

            HStack(alignment: .top, spacing: 18) {
                framingCanvas(sourceWidth: dims.width, sourceHeight: dims.height, spec: activeSpec)
                    .frame(width: 360, height: 240)

                VStack(alignment: .leading, spacing: 8) {
                    Text("Centered Even-Pixel Delivery Crops")
                        .font(.subheadline.weight(.semibold))

                    ForEach(specs) { spec in
                        let isSelected = spec.aspect == appState.previewAspect.rawValue
                        HStack(spacing: 8) {
                            Text(spec.aspect)
                                .font(.caption.weight(.bold).monospaced())
                                .frame(width: 52, alignment: .leading)
                            Text("\(spec.width)x\(spec.height)")
                                .font(.caption.monospaced())
                                .frame(width: 82, alignment: .leading)
                            Text("offset (\(spec.x), \(spec.y))")
                                .font(.caption.monospaced())
                                .foregroundStyle(.secondary)
                            Spacer()
                            Text(spec.ffmpegCrop)
                                .font(.caption2.monospaced())
                                .foregroundStyle(.secondary)
                        }
                        .padding(.horizontal, 8)
                        .padding(.vertical, 5)
                        .background(isSelected ? Color.accentColor.opacity(0.14) : Color.clear)
                        .clipShape(RoundedRectangle(cornerRadius: 6))
                        .onTapGesture {
                            if let matched = DeliveryAspect(rawValue: spec.aspect) {
                                appState.previewAspect = matched
                            }
                        }
                    }

                    if let activeSpec {
                        Divider()
                        Text("Active Crop: \(activeSpec.label) — \(activeSpec.width)x\(activeSpec.height)")
                            .font(.caption.weight(.semibold))
                        if let action = activeSpec.actionSafe, let title = activeSpec.titleSafe {
                            Text("90% Action Safe: \(action.width)x\(action.height)  •  80% Title Safe: \(title.width)x\(title.height)")
                                .font(.caption.monospaced())
                                .foregroundStyle(.secondary)
                        }
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 10).fill(Color(nsColor: .controlBackgroundColor)))
        .overlay(RoundedRectangle(cornerRadius: 10).stroke(Color.secondary.opacity(0.20), lineWidth: 1))
    }

    private func framingCanvas(sourceWidth: Int, sourceHeight: Int, spec: DeliveryCropSpec?) -> some View {
        GeometryReader { geo in
            let frameW = geo.size.width
            let frameH = frameW * (Double(sourceHeight) / Double(max(sourceWidth, 1)))
            let displayH = min(frameH, geo.size.height)
            let displayW = displayH * (Double(sourceWidth) / Double(max(sourceHeight, 1)))

            ZStack(alignment: .topLeading) {
                RoundedRectangle(cornerRadius: 6)
                    .fill(Color.black.opacity(0.85))
                    .frame(width: displayW, height: displayH)

                if let spec {
                    let cropW = displayW * spec.normRect.width
                    let cropH = displayH * spec.normRect.height
                    let cropX = displayW * spec.normRect.x
                    let cropY = displayH * spec.normRect.y

                    Rectangle()
                        .fill(Color.accentColor.opacity(0.16))
                        .overlay(
                            Rectangle()
                                .stroke(Color.accentColor, lineWidth: 2)
                        )
                        .frame(width: cropW, height: cropH)
                        .offset(x: cropX, y: cropY)

                    if appState.previewShowActionSafe, let action = spec.actionSafe {
                        Rectangle()
                            .stroke(Color.yellow.opacity(0.85), style: StrokeStyle(lineWidth: 1, dash: [5, 3]))
                            .frame(
                                width: displayW * action.normRect.width,
                                height: displayH * action.normRect.height
                            )
                            .offset(
                                x: displayW * action.normRect.x,
                                y: displayH * action.normRect.y
                            )
                    }

                    if appState.previewShowTitleSafe, let title = spec.titleSafe {
                        Rectangle()
                            .stroke(Color.green.opacity(0.85), style: StrokeStyle(lineWidth: 1, dash: [3, 3]))
                            .frame(
                                width: displayW * title.normRect.width,
                                height: displayH * title.normRect.height
                            )
                            .offset(
                                x: displayW * title.normRect.x,
                                y: displayH * title.normRect.y
                            )
                    }

                    Text("\(spec.aspect) (\(spec.width)x\(spec.height))")
                        .font(.caption2.weight(.bold).monospaced())
                        .foregroundStyle(.white)
                        .padding(.horizontal, 6)
                        .padding(.vertical, 2)
                        .background(Color.black.opacity(0.65))
                        .clipShape(RoundedRectangle(cornerRadius: 4))
                        .offset(x: cropX + 6, y: cropY + 6)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)
        }
    }

    private var activePreviewDimensions: (width: Int, height: Int, label: String) {
        if let clips = appState.ingestResult?.clips {
            if let selId = appState.selectedIngestedClipId,
               let clip = clips.first(where: { $0.id == selId }),
               clip.width >= 2, clip.height >= 2 {
                return (clip.width, clip.height, clip.filename)
            }
            if let firstValid = clips.first(where: { $0.width >= 2 && $0.height >= 2 }) {
                return (firstValid.width, firstValid.height, firstValid.filename)
            }
        }
        if let clip = appState.clipResult, clip.width >= 2, clip.height >= 2 {
            return (clip.width, clip.height, "Clip Inspector")
        }
        return (3840, 2560, "Default 3:2 Open Gate")
    }

    // MARK: - 3. Relink-Verified Proxy Export

    private var proxyExportCard: some View {
        let selectedCount = appState.selectedProxyClipPaths.count

        return VStack(alignment: .leading, spacing: 12) {
            HStack {
                Label("3. Relink-Verified Proxy Export (ffmpeg)", systemImage: "film.stack")
                    .font(.headline)
                Spacer()
                Text("\(selectedCount) clip(s) selected")
                    .font(.caption.monospaced())
                    .foregroundStyle(.secondary)
            }

            HStack(spacing: 8) {
                Image(systemName: "info.circle.fill")
                    .foregroundStyle(.orange)
                Text("Originals are never modified (SHA-256 verified). ffmpeg proxies omit Sony rtmd gyro streams — relink to camera originals for Gyroflow/Catalyst stabilization.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            .padding(8)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color.orange.opacity(0.10))
            .clipShape(RoundedRectangle(cornerRadius: 6))

            HStack(spacing: 12) {
                Button {
                    chooseProxyOutFolder()
                } label: {
                    Label("Select Proxy Output Folder...", systemImage: "folder.badge.plus")
                }
                .buttonStyle(.bordered)

                if let outDir = appState.proxyOutDirURL {
                    Text(outDir.path)
                        .font(.caption.monospaced())
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                        .truncationMode(.middle)
                } else {
                    Text("Choose destination folder for proxies + proxy_manifest.json")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }

            HStack(spacing: 12) {
                Picker("Aspect", selection: $appState.proxyAspect) {
                    ForEach(ProxyAspectOption.allCases) { opt in
                        Text(opt.rawValue).tag(opt)
                    }
                }
                .frame(width: 150)

                Picker("Resolution", selection: $appState.proxyResolution) {
                    ForEach(ProxyResolutionOption.allCases) { res in
                        Text(res.rawValue).tag(res)
                    }
                }
                .frame(width: 140)

                Picker("Codec", selection: $appState.proxyCodec) {
                    ForEach(ProxyCodecOption.allCases) { c in
                        Text(c.displayName).tag(c)
                    }
                }
                .frame(width: 220)

                Toggle("Copy *M01.XML (3:2)", isOn: $appState.proxyPreserveSidecar)
                    .toggleStyle(.checkbox)

                Toggle("Dry Run", isOn: $appState.proxyDryRun)
                    .toggleStyle(.checkbox)

                Spacer()

                Button {
                    Task { await appState.generateProxiesForSelectedClips() }
                } label: {
                    HStack(spacing: 6) {
                        if appState.isGeneratingProxies {
                            ProgressView().controlSize(.small)
                        } else {
                            Image(systemName: "play.rectangle.on.rectangle")
                        }
                        Text(appState.proxyDryRun ? "Plan Proxies" : "Generate Proxies")
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(selectedCount == 0 || appState.proxyOutDirURL == nil || appState.isGeneratingProxies)
            }

            if let err = appState.proxyError {
                Label(err, systemImage: "exclamationmark.triangle.fill")
                    .font(.callout)
                    .foregroundStyle(.red)
            }

            if let proxyRes = appState.proxyResult {
                VStack(alignment: .leading, spacing: 8) {
                    HStack {
                        Text(
                            proxyRes.dryRun
                                ? "Dry-Run Plan: \(proxyRes.totalInputs) proxy job(s) -> \(proxyRes.targetWidth)x\(proxyRes.targetHeight) (\(proxyRes.codec))"
                                : "Generated \(proxyRes.succeededCount)/\(proxyRes.totalInputs) proxies (\(proxyRes.targetWidth)x\(proxyRes.targetHeight) \(proxyRes.codec))"
                        )
                        .font(.callout.weight(.semibold))
                        .foregroundStyle(proxyRes.ok ? .green : .red)

                        Spacer()

                        if !proxyRes.dryRun {
                            Button("Reveal Manifest") {
                                NSWorkspace.shared.selectFile(proxyRes.manifestPath, inFileViewerRootedAtPath: proxyRes.outDir)
                            }
                            .buttonStyle(.bordered)
                            .controlSize(.small)
                        }
                    }

                    ForEach(proxyRes.proxies) { item in
                        proxyResultRow(item)
                    }
                }
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 10).fill(Color(nsColor: .controlBackgroundColor)))
        .overlay(RoundedRectangle(cornerRadius: 10).stroke(Color.secondary.opacity(0.20), lineWidth: 1))
    }

    private func proxyResultRow(_ item: GeneratedProxyItem) -> some View {
        let rv = item.relinkVerification
        return VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 8) {
                Image(systemName: item.ok ? "checkmark.seal.fill" : "xmark.seal.fill")
                    .foregroundStyle(item.ok ? .green : .red)
                Text(URL(fileURLWithPath: item.outputFile).lastPathComponent)
                    .font(.callout.weight(.semibold).monospaced())
                Spacer()
                if item.relinkToOriginalForGyro {
                    Text("Relink to Original for Gyro")
                        .font(.caption2.weight(.semibold))
                        .padding(.horizontal, 6)
                        .padding(.vertical, 2)
                        .background(Color.orange.opacity(0.15))
                        .foregroundStyle(.orange)
                        .clipShape(Capsule())
                }
            }
            if let err = item.error {
                Text(err)
                    .font(.caption)
                    .foregroundStyle(.red)
            } else {
                HStack(spacing: 12) {
                    Text("FPS match: \(boolLabel(rv.fpsMatch))")
                    Text("Dur delta: \(rv.durationDeltaSec.map { String(format: "%.3fs", $0) } ?? "planned")")
                    Text("TC match: \(boolLabel(rv.timecodeMatch))")
                    Text("Audio ch: \(boolLabel(rv.audioChannelsMatch))")
                    Text("Orig SHA unchanged: \(rv.originalSha256Unchanged ? "YES" : "NO")")
                    Text("Sidecar: \(item.sidecarCopied == true ? "Copied" : "Skipped")")
                }
                .font(.caption2.monospaced())
                .foregroundStyle(.secondary)
            }
        }
        .padding(8)
        .background(RoundedRectangle(cornerRadius: 8).fill(Color(nsColor: .windowBackgroundColor)))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.secondary.opacity(0.15), lineWidth: 1))
    }

    // MARK: - 4. One-Click Gyroflow Preset Installer

    private var gyroflowPresetsCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Label("4. One-Click Gyroflow 3:2 Lens Profile Installer", systemImage: "gyroscope")
                    .font(.headline)
                Spacer()
                Button {
                    Task { await appState.loadGyroflowPresets() }
                } label: {
                    if appState.isLoadingGyroPresets {
                        ProgressView().controlSize(.small)
                    } else {
                        Label("Refresh Profiles", systemImage: "arrow.clockwise")
                    }
                }
                .buttonStyle(.bordered)
                .controlSize(.small)

                Button {
                    Task { await appState.installGyroflowPresets(targetDir: nil) }
                } label: {
                    HStack(spacing: 6) {
                        if appState.isInstallingGyroPresets {
                            ProgressView().controlSize(.small)
                        } else {
                            Image(systemName: "square.and.arrow.down")
                        }
                        Text("Install to Gyroflow")
                    }
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.small)
                .disabled(appState.isInstallingGyroPresets)
            }

            if let err = appState.gyroPresetError {
                Label(err, systemImage: "exclamationmark.triangle.fill")
                    .font(.callout)
                    .foregroundStyle(.red)
            }

            if let list = appState.gyroPresetList {
                ForEach(list.presets) { preset in
                    HStack(spacing: 10) {
                        Image(systemName: "doc.badge.gearshape")
                            .foregroundStyle(.blue)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(preset.filename)
                                .font(.callout.weight(.medium).monospaced())
                            Text("\(preset.cameraModel) • \(preset.dimension) • Readout: \(preset.frameReadoutTimeMs.map { String(format: "%.2f ms", $0) } ?? "—")")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                        Spacer()
                        Text(preset.evidenceLevel)
                            .font(.caption2.monospaced())
                            .padding(.horizontal, 8)
                            .padding(.vertical, 3)
                            .background(
                                preset.evidenceLevel == "hardware_measured"
                                    ? Color.green.opacity(0.15)
                                    : Color.orange.opacity(0.15)
                            )
                            .foregroundStyle(
                                preset.evidenceLevel == "hardware_measured" ? .green : .orange
                            )
                            .clipShape(Capsule())
                    }
                    .padding(8)
                    .background(RoundedRectangle(cornerRadius: 8).fill(Color(nsColor: .windowBackgroundColor)))
                }
            } else if !appState.isLoadingGyroPresets {
                Text("Starter Gyroflow 3:2 lens profiles will appear here once studio_gyro presets are loaded.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            if let installed = appState.gyroPresetInstallResult {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Installed \(installed.installedCount) Gyroflow preset(s) to:")
                        .font(.callout.weight(.semibold))
                        .foregroundStyle(.green)
                    Text(installed.targetDir)
                        .font(.caption.monospaced())
                        .foregroundStyle(.secondary)
                        .textSelection(.enabled)
                }
                .padding(10)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(Color.green.opacity(0.08))
                .clipShape(RoundedRectangle(cornerRadius: 8))
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 10).fill(Color(nsColor: .controlBackgroundColor)))
        .overlay(RoundedRectangle(cornerRadius: 10).stroke(Color.secondary.opacity(0.20), lineWidth: 1))
    }

    // MARK: - Helpers

    private func summaryPill(title: String, value: String, color: Color) -> some View {
        HStack(spacing: 5) {
            Text(title)
                .foregroundStyle(.secondary)
            Text(value)
                .fontWeight(.bold)
                .foregroundStyle(color)
        }
        .font(.caption.monospaced())
        .padding(.horizontal, 10)
        .padding(.vertical, 4)
        .background(color.opacity(0.10))
        .clipShape(Capsule())
    }

    private func miniBadge(label: String, ok: Bool) -> some View {
        Text(label)
            .font(.caption2.weight(.semibold).monospaced())
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(ok ? Color.green.opacity(0.14) : Color.red.opacity(0.14))
            .foregroundStyle(ok ? .green : .red)
            .clipShape(Capsule())
    }

    private func boolLabel(_ val: Bool?) -> String {
        guard let val else { return "planned" }
        return val ? "YES" : "NO"
    }

    private func chooseIngestFolder() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        panel.message = "Select SD Card root or PRIVATE/M4ROOT/CLIP folder to batch-inspect"
        if panel.runModal() == .OK, let url = panel.url {
            appState.ingestRootURL = url
            Task { await appState.runBatchIngest() }
        }
    }

    private func chooseProxyOutFolder() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        panel.canCreateDirectories = true
        panel.message = "Select destination folder for generated editing proxies"
        if panel.runModal() == .OK, let url = panel.url {
            appState.proxyOutDirURL = url
        }
    }
}
