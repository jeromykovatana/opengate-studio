import AppKit
import OpenGateStudioCore
import SwiftUI
import UniformTypeIdentifiers

public struct ClipInspectorView: View {
    @EnvironmentObject private var appState: AppState
    @State private var isDropTargeted: Bool = false

    public init() {}

    public var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                dropZoneCard

                if let clipError = appState.clipError {
                    HStack(spacing: 8) {
                        Image(systemName: "exclamationmark.triangle.fill")
                            .foregroundStyle(.red)
                        Text(clipError)
                            .font(.callout)
                        Spacer()
                    }
                    .padding(12)
                    .background(Color.red.opacity(0.12))
                    .clipShape(RoundedRectangle(cornerRadius: 8))
                }

                if let result = appState.clipResult {
                    verdictHeader(result)
                    statusCardsGrid(result)
                    metadataDetailsCard(result)
                } else {
                    emptyStatePlaceholder
                }
            }
            .padding(20)
        }
    }

    private var dropZoneCard: some View {
        VStack(spacing: 12) {
            Image(systemName: isDropTargeted ? "arrow.down.doc.fill" : "film")
                .font(.system(size: 34))
                .foregroundStyle(isDropTargeted ? Color.accentColor : Color.secondary)

            Text("Drop a Sony XAVC .MP4 Clip Here")
                .font(.headline)

            Text("Matching *M01.XML sidecar next to the clip is auto-detected for 3:2 Gyroflow/Catalyst inspection.")
                .font(.caption)
                .foregroundStyle(.secondary)

            HStack(spacing: 12) {
                Button {
                    chooseMP4File()
                } label: {
                    Label("Select MP4 Clip...", systemImage: "folder")
                }
                .buttonStyle(.borderedProminent)

                Button {
                    chooseXMLFile()
                } label: {
                    Label("Select Sidecar XML...", systemImage: "doc.text")
                }
                .buttonStyle(.bordered)
                .disabled(appState.selectedMP4URL == nil)

                if appState.selectedMP4URL != nil {
                    Button {
                        Task { await appState.inspectCurrentClip() }
                    } label: {
                        if appState.isCheckingClip {
                            ProgressView().controlSize(.small)
                        } else {
                            Label("Re-Check", systemImage: "arrow.clockwise")
                        }
                    }
                    .buttonStyle(.bordered)
                }
            }

            if let mp4 = appState.selectedMP4URL {
                VStack(spacing: 4) {
                    Text("MP4: \(mp4.path)")
                        .font(.caption.monospaced())
                        .lineLimit(1)
                        .truncationMode(.middle)
                    if let xml = appState.selectedXMLURL {
                        Text("XML: \(xml.path)")
                            .font(.caption.monospaced())
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                            .truncationMode(.middle)
                    } else {
                        Text("XML: None selected (checking embedded NRT metadata if present)")
                            .font(.caption.monospaced())
                            .foregroundStyle(.secondary)
                    }
                }
                .padding(.top, 4)
            }
        }
        .frame(maxWidth: .infinity)
        .padding(24)
        .background(
            RoundedRectangle(cornerRadius: 12)
                .fill(isDropTargeted ? Color.accentColor.opacity(0.10) : Color(nsColor: .controlBackgroundColor))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 12)
                .strokeBorder(
                    isDropTargeted ? Color.accentColor : Color.secondary.opacity(0.30),
                    style: StrokeStyle(lineWidth: 1.5, dash: [6, 4])
                )
        )
        .onDrop(of: [.fileURL], isTargeted: $isDropTargeted) { providers in
            handleDrop(providers: providers)
        }
    }

    private func verdictHeader(_ result: ClipCheckResult) -> some View {
        HStack(spacing: 10) {
            Image(systemName: result.ok ? "checkmark.seal.fill" : "xmark.seal.fill")
                .font(.title2)
                .foregroundStyle(result.ok ? .green : .red)
            VStack(alignment: .leading, spacing: 2) {
                Text(result.ok ? "Native 3:2 Open-Gate Clip Verified" : "Clip Verification Issues Found")
                    .font(.headline)
                Text("Codec: \(result.codec)  •  FPS: \(result.fps)  •  Display Aspect: \(result.displayAspect)")
                    .font(.caption.monospaced())
                    .foregroundStyle(.secondary)
            }
            Spacer()
        }
        .padding(14)
        .background(result.ok ? Color.green.opacity(0.10) : Color.red.opacity(0.10))
        .clipShape(RoundedRectangle(cornerRadius: 10))
    }

    private func statusCardsGrid(_ result: ClipCheckResult) -> some View {
        let containerOK = result.width == 3840 && result.height == 2560
        let xmlStatus: Bool? = result.xml3x2

        return LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 14) {
            inspectorStatusCard(
                title: "3840x2560 Container",
                passed: containerOK,
                detail: "Dimensions: \(result.width)x\(result.height) (\(result.displayAspect))"
            )

            inspectorStatusCard(
                title: "Sony VPRF 3:2",
                passed: result.vprf3x2,
                detail: result.vprf3x2 ? "VPRF / PROF 3:2 profile verified" : "VPRF 3:2 profile missing or mismatched"
            )

            inspectorStatusCard(
                title: "M01.XML / NRT 3:2 (Gyroflow Ready)",
                passed: xmlStatus == true,
                detail: xmlStatus == true
                    ? "Native 3:2 layout confirmed (16:9 tag suppressed)"
                    : (xmlStatus == false ? "XML reports non-3:2 or 16:9 aspect" : "No sidecar/embedded XML detected")
            )

            inspectorStatusCard(
                title: "rtmd Gyro Track",
                passed: result.rtmdGyroPresent && result.rtmdSamples > 0,
                detail: result.rtmdGyroPresent
                    ? "\(result.rtmdSamples) rtmd timed-metadata samples present"
                    : "No rtmd gyro track detected"
            )
        }
    }

    private func inspectorStatusCard(title: String, passed: Bool, detail: String) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: passed ? "checkmark.circle.fill" : "xmark.circle.fill")
                .font(.title2)
                .foregroundStyle(passed ? .green : .red)

            VStack(alignment: .leading, spacing: 4) {
                Text(title)
                    .font(.headline)
                Text(detail)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Spacer()
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 10)
                .fill(passed ? Color.green.opacity(0.08) : Color.red.opacity(0.08))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 10)
                .stroke(passed ? Color.green.opacity(0.35) : Color.red.opacity(0.35), lineWidth: 1)
        )
    }

    private func metadataDetailsCard(_ result: ClipCheckResult) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Inspection Details")
                .font(.headline)

            if result.issues.isEmpty {
                Label("Zero structural, aspect, or gyro issues reported.", systemImage: "checkmark.circle")
                    .font(.callout)
                    .foregroundStyle(.green)
            } else {
                ForEach(result.issues, id: \.self) { issue in
                    Label(issue, systemImage: "exclamationmark.triangle")
                        .font(.callout)
                        .foregroundStyle(.red)
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

    private var emptyStatePlaceholder: some View {
        HStack {
            Spacer()
            VStack(spacing: 8) {
                Image(systemName: "waveform.and.magnifyingglass")
                    .font(.largeTitle)
                    .foregroundStyle(.secondary)
                Text("Choose an .MP4 clip above to inspect container dimensions, VPRF, XML aspect, and rtmd gyro metadata.")
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
            }
            .padding(24)
            Spacer()
        }
    }

    private func chooseMP4File() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.mpeg4Movie, UTType(filenameExtension: "mp4") ?? .movie]
        panel.allowsMultipleSelection = false
        panel.canChooseDirectories = false
        panel.message = "Select a Sony XAVC .MP4 clip to inspect"
        if panel.runModal() == .OK, let url = panel.url {
            Task { await appState.selectMP4File(url) }
        }
    }

    private func chooseXMLFile() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.xml]
        panel.allowsMultipleSelection = false
        panel.canChooseDirectories = false
        panel.message = "Select an optional Sony *M01.XML sidecar file"
        if panel.runModal() == .OK, let url = panel.url {
            Task { await appState.selectXMLFile(url) }
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
                if url.pathExtension.lowercased() == "xml" {
                    await appState.selectXMLFile(url)
                } else {
                    await appState.selectMP4File(url)
                }
            }
        }
        return true
    }
}
