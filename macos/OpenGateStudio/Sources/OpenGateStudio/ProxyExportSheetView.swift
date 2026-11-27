import AppKit
import OpenGateStudioCore
import SwiftUI

public struct ProxyExportSheetView: View {
    @EnvironmentObject private var appState: AppState
    @Environment(\.dismiss) private var dismiss
    @State private var showAdvanced: Bool = false

    public init() {}

    private var selectedCount: Int {
        if appState.ingestResult != nil {
            return appState.selectedProxyClipPaths.count
        }
        return appState.selectedMP4URL != nil ? 1 : 0
    }

    public var body: some View {
        VStack(spacing: 0) {
            sheetHeader
            Divider()

            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    StudioCallout(
                        icon: "shield.checkered",
                        color: .blue,
                        title: "Originals Are Never Modified (SHA-256 Verified)",
                        detail: "ffmpeg editing proxies omit Sony rtmd gyro streams. Relink to your camera originals in your NLE or Gyroflow for gyro stabilization."
                    )

                    destinationCard
                    formatSettingsCard
                    advancedDisclosure

                    if let err = appState.proxyError {
                        StudioCallout(
                            icon: "exclamationmark.triangle.fill",
                            color: .red,
                            title: "Proxy Generation Error",
                            detail: err
                        )
                    }

                    if let proxyRes = appState.proxyResult {
                        resultsCard(proxyRes)
                    }
                }
                .padding(20)
            }

            Divider()
            sheetFooter
        }
        .frame(minWidth: 540, idealWidth: 580, minHeight: 480, idealHeight: 560)
    }

    private var sheetHeader: some View {
        HStack(spacing: 12) {
            Image(systemName: "square.and.arrow.up")
                .font(.title2)
                .foregroundStyle(Color.accentColor)
                .frame(width: 34, height: 34)
                .background(Color.accentColor.opacity(0.12))
                .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))

            VStack(alignment: .leading, spacing: 2) {
                Text("Export Editing Proxies")
                    .font(.headline)
                Text("\(selectedCount) clip(s) queued for relink-verified proxy export.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Spacer()
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 14)
        .background(.bar)
    }

    private var destinationCard: some View {
        StudioSurface(padding: 14) {
            HStack(spacing: 12) {
                VStack(alignment: .leading, spacing: 3) {
                    Text("Output Folder")
                        .font(.subheadline.weight(.semibold))
                    if let outDir = appState.proxyOutDirURL {
                        Text(outDir.path)
                            .font(.caption.monospaced())
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                            .truncationMode(.middle)
                    } else {
                        Text("Choose a destination folder for proxies and proxy_manifest.json.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }

                Spacer()

                Button("Choose Folder…") {
                    chooseProxyOutFolder()
                }
                .buttonStyle(.bordered)
            }
        }
    }

    private var formatSettingsCard: some View {
        StudioSurface(padding: 14) {
            VStack(alignment: .leading, spacing: 12) {
                Text("Proxy Settings")
                    .font(.subheadline.weight(.semibold))

                HStack(spacing: 12) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Aspect")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Picker("Aspect", selection: $appState.proxyAspect) {
                            ForEach(ProxyAspectOption.allCases) { opt in
                                Text(opt.rawValue).tag(opt)
                            }
                        }
                        .labelsHidden()
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)

                    VStack(alignment: .leading, spacing: 4) {
                        Text("Resolution")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Picker("Resolution", selection: $appState.proxyResolution) {
                            ForEach(ProxyResolutionOption.allCases) { res in
                                Text(res.rawValue).tag(res)
                            }
                        }
                        .labelsHidden()
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)

                    VStack(alignment: .leading, spacing: 4) {
                        Text("Codec")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Picker("Codec", selection: $appState.proxyCodec) {
                            ForEach(ProxyCodecOption.allCases) { codec in
                                Text(codec.displayName).tag(codec)
                            }
                        }
                        .labelsHidden()
                    }
                    .frame(minWidth: 190, alignment: .leading)
                }

                Divider()

                Toggle("Copy *M01.XML sidecar (3:2) next to proxies", isOn: $appState.proxyPreserveSidecar)
                    .font(.callout)
            }
        }
    }

    private var advancedDisclosure: some View {
        StudioSurface(padding: 14) {
            DisclosureGroup("Advanced", isExpanded: $showAdvanced) {
                Toggle("Dry Run (generate plan & manifest without encoding)", isOn: $appState.proxyDryRun)
                    .font(.callout)
                    .padding(.top, 8)
            }
            .font(.subheadline.weight(.semibold))
        }
    }

    private func resultsCard(_ proxyRes: ProxyGenerationResult) -> some View {
        StudioSurface(accent: proxyRes.ok ? .green : .red, padding: 14) {
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    Text(
                        proxyRes.dryRun
                            ? "Dry-Run Plan: \(proxyRes.totalInputs) proxy job(s) -> \(proxyRes.targetWidth)×\(proxyRes.targetHeight)"
                            : "Generated \(proxyRes.succeededCount)/\(proxyRes.totalInputs) proxies (\(proxyRes.targetWidth)×\(proxyRes.targetHeight))"
                    )
                    .font(.callout.weight(.semibold))
                    .foregroundStyle(proxyRes.ok ? .green : .red)

                    Spacer()

                    if !proxyRes.dryRun {
                        Button("Reveal in Finder") {
                            NSWorkspace.shared.selectFile(proxyRes.manifestPath, inFileViewerRootedAtPath: proxyRes.outDir)
                        }
                        .buttonStyle(.bordered)
                        .controlSize(.small)
                    }
                }

                ForEach(proxyRes.proxies) { item in
                    Divider()
                    let rv = item.relinkVerification
                    VStack(alignment: .leading, spacing: 4) {
                        HStack(spacing: 6) {
                            Image(systemName: item.ok ? "checkmark.circle.fill" : "xmark.circle.fill")
                                .foregroundStyle(item.ok ? .green : .red)
                            Text(URL(fileURLWithPath: item.outputFile).lastPathComponent)
                                .font(.callout.weight(.medium))
                            Spacer()
                            if rv.relinkOk == true {
                                StudioStatusPill("Relink Verified", color: .green)
                            }
                        }
                        if let err = item.error {
                            Text(err)
                                .font(.caption)
                                .foregroundStyle(.red)
                        } else {
                            Text("FPS match: \(boolLabel(rv.fpsMatch)) · Timecode: \(boolLabel(rv.timecodeMatch)) · Audio: \(boolLabel(rv.audioChannelsMatch)) · Original unchanged: \(rv.originalSha256Unchanged ? "Yes" : "No")")
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                        }
                    }
                }
            }
        }
    }

    private var sheetFooter: some View {
        HStack {
            Button("Close") {
                dismiss()
            }
            .keyboardShortcut(.cancelAction)

            Spacer()

            Button {
                ensureSingleClipQueuedIfNeeded()
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
            .keyboardShortcut(.defaultAction)
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 14)
        .background(.bar)
    }

    private func ensureSingleClipQueuedIfNeeded() {
        if appState.ingestResult == nil, let mp4 = appState.selectedMP4URL {
            appState.selectedProxyClipPaths = [mp4.path]
        }
    }

    private func boolLabel(_ val: Bool?) -> String {
        guard let val else { return "Planned" }
        return val ? "Yes" : "No"
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
