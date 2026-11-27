import AppKit
import OpenGateStudioCore
import SwiftUI
import UniformTypeIdentifiers

public struct ClipInspectorPanel: View {
    @EnvironmentObject private var appState: AppState
    @State private var showTechnicalDetails: Bool = false

    public init() {}

    public var body: some View {
        Group {
            if let single = appState.clipResult {
                inspectorScrollBody(
                    isBatch: false,
                    filename: appState.selectedMP4URL?.lastPathComponent ?? "Clip",
                    width: single.width,
                    height: single.height,
                    displayAspect: single.displayAspect,
                    vprf3x2: single.vprf3x2,
                    xml3x2: single.xml3x2,
                    rtmdPresent: single.rtmdGyroPresent,
                    rtmdSamples: single.rtmdSamples,
                    codec: single.codecProfileLevel ?? single.codec,
                    fps: single.fps,
                    cadenceConstant: single.cadenceConstant,
                    durationSec: single.durationSec,
                    avgBitrateMbps: single.avgBitrateMbps,
                    readyForGyroflow: appState.gyroDiagResult?.readyForGyroflow,
                    readyForCatalyst: appState.gyroDiagResult?.readyForCatalyst,
                    gyroSummary: appState.gyroDiagResult?.summary,
                    recommendedActions: appState.gyroDiagResult?.recommendedActions ?? [],
                    failureCategory: appState.gyroDiagResult?.failureCategory,
                    readoutMs: appState.gyroDiagResult?.readoutTimeMs,
                    evidenceLevel: appState.gyroDiagResult?.evidenceLevel
                )
            } else if let batchClip = appState.activeInspectedBatchClip {
                inspectorScrollBody(
                    isBatch: true,
                    filename: batchClip.filename,
                    width: batchClip.width,
                    height: batchClip.height,
                    displayAspect: batchClip.displayAspect,
                    vprf3x2: batchClip.vprf3x2,
                    xml3x2: batchClip.xml3x2,
                    rtmdPresent: batchClip.rtmdGyroPresent,
                    rtmdSamples: batchClip.rtmdSamples,
                    codec: batchClip.codecProfileLevel ?? batchClip.codec,
                    fps: batchClip.fps,
                    cadenceConstant: batchClip.cadenceConstant,
                    durationSec: batchClip.durationSec,
                    avgBitrateMbps: batchClip.avgBitrateMbps,
                    readyForGyroflow: appState.gyroDiagResult?.readyForGyroflow ?? batchClip.readyForGyroflow,
                    readyForCatalyst: appState.gyroDiagResult?.readyForCatalyst ?? batchClip.readyForCatalyst,
                    gyroSummary: appState.gyroDiagResult?.summary ?? batchClip.gyroSummary,
                    recommendedActions: appState.gyroDiagResult?.recommendedActions ?? batchClip.recommendedActions,
                    failureCategory: appState.gyroDiagResult?.failureCategory ?? batchClip.failureCategory,
                    readoutMs: appState.gyroDiagResult?.readoutTimeMs,
                    evidenceLevel: appState.gyroDiagResult?.evidenceLevel
                )
            } else {
                ContentUnavailableView(
                    "No Clip Selected",
                    systemImage: "film",
                    description: Text("Open an MP4 clip or SD card folder to inspect 3:2 metadata and Gyroflow readiness.")
                )
            }
        }
        .background(Color(nsColor: .windowBackgroundColor))
    }

    private func inspectorScrollBody(
        isBatch: Bool,
        filename: String,
        width: Int,
        height: Int,
        displayAspect: String,
        vprf3x2: Bool,
        xml3x2: Bool?,
        rtmdPresent: Bool,
        rtmdSamples: Int,
        codec: String,
        fps: String,
        cadenceConstant: Bool?,
        durationSec: Double?,
        avgBitrateMbps: Double?,
        readyForGyroflow: Bool?,
        readyForCatalyst: Bool?,
        gyroSummary: String?,
        recommendedActions: [String],
        failureCategory: String?,
        readoutMs: Double?,
        evidenceLevel: String?
    ) -> some View {
        let isStock = (isBatch ? appState.ingestExpectMode == "stock" : appState.clipExpectMode == "stock")
        let containerOk = isStock
            ? ((width == 3840 || width == 4096) && height == 2160)
            : ((width == 3840 && height == 2560) || (width == 5760 && height == 3840))

        return ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                headerSection(isBatch: isBatch, filename: filename)

                Divider()

                checksSection(
                    containerOk: containerOk,
                    containerDetail: "\(width)×\(height) (\(displayAspect))",
                    vprf3x2: vprf3x2,
                    xml3x2: xml3x2,
                    rtmdPresent: rtmdPresent,
                    rtmdSamples: rtmdSamples
                )

                Divider()

                gyroReadinessSection(
                    isBatch: isBatch,
                    readyForGyroflow: readyForGyroflow,
                    readyForCatalyst: readyForCatalyst,
                    summary: gyroSummary,
                    recommendedActions: recommendedActions
                )

                Divider()

                DisclosureGroup("Technical Details", isExpanded: $showTechnicalDetails) {
                    VStack(alignment: .leading, spacing: 8) {
                        detailRow("Codec", codec)
                        detailRow("Frame Rate", "\(fps) (\(cadenceConstant == false ? "Variable" : "Constant"))")
                        if let durationSec {
                            detailRow("Duration", String(format: "%.2f s", durationSec))
                        }
                        if let avgBitrateMbps {
                            detailRow("Avg Bitrate", String(format: "%.1f Mbps", avgBitrateMbps))
                        }
                        if let readoutMs {
                            detailRow("Readout Time", String(format: "%.2f ms (%@)", readoutMs, evidenceLevel ?? "estimated"))
                        }
                        if let failureCategory {
                            detailRow("Gyro Category", failureCategory)
                        }
                        if let mp4 = appState.selectedMP4URL {
                            detailRow("MP4 Path", mp4.path, monospaced: true)
                        }
                        if let xml = appState.selectedXMLURL {
                            detailRow("XML Path", xml.path, monospaced: true)
                        }
                    }
                    .padding(.top, 8)
                }
                .font(.subheadline.weight(.semibold))
            }
            .padding(16)
        }
    }

    private func headerSection(isBatch: Bool, filename: String) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(filename)
                .font(.headline)
                .lineLimit(1)
                .truncationMode(.middle)

            if !isBatch {
                Picker("Expect", selection: $appState.clipExpectMode) {
                    Text("Open-Gate 3:2").tag("open-gate")
                    Text("Stock 16:9").tag("stock")
                }
                .pickerStyle(.segmented)
                .controlSize(.small)
                .onChange(of: appState.clipExpectMode) { _, _ in
                    if appState.selectedMP4URL != nil {
                        Task {
                            await appState.inspectCurrentClip()
                            await appState.runGyroDiagnosticForCurrentClip()
                        }
                    }
                }

                HStack(spacing: 8) {
                    Button {
                        chooseXMLFile()
                    } label: {
                        Label("Sidecar XML…", systemImage: "doc.text")
                    }
                    .buttonStyle(.bordered)
                    .controlSize(.small)

                    Button {
                        Task {
                            await appState.inspectCurrentClip()
                            await appState.runGyroDiagnosticForCurrentClip()
                        }
                    } label: {
                        if appState.isCheckingClip {
                            ProgressView().controlSize(.small)
                        } else {
                            Label("Re-Check", systemImage: "arrow.clockwise")
                        }
                    }
                    .buttonStyle(.bordered)
                    .controlSize(.small)
                    .disabled(appState.selectedMP4URL == nil || appState.isCheckingClip)
                }
            }
        }
    }

    private func checksSection(
        containerOk: Bool,
        containerDetail: String,
        vprf3x2: Bool,
        xml3x2: Bool?,
        rtmdPresent: Bool,
        rtmdSamples: Int
    ) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("3:2 & Metadata Checks")
                .font(.subheadline.weight(.semibold))

            checkRow(title: "Container Dimensions", passed: containerOk, detail: containerDetail)
            checkRow(
                title: "Sony VPRF Profile",
                passed: vprf3x2,
                detail: vprf3x2 ? "3:2 verified" : "Missing or mismatched"
            )
            checkRow(
                title: "M01.XML / NRT Aspect",
                passed: xml3x2 == true,
                detail: xml3x2 == true ? "3:2 confirmed" : (xml3x2 == false ? "Non-3:2 / 16:9 tag" : "No XML detected")
            )
            checkRow(
                title: "rtmd Gyro Track",
                passed: rtmdPresent && rtmdSamples > 0,
                detail: rtmdPresent ? "\(rtmdSamples) samples" : "Not present"
            )
        }
    }

    private func gyroReadinessSection(
        isBatch: Bool,
        readyForGyroflow: Bool?,
        readyForCatalyst: Bool?,
        summary: String?,
        recommendedActions: [String]
    ) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text("Stabilization Readiness")
                    .font(.subheadline.weight(.semibold))
                Spacer()
                Button {
                    Task { await appState.runGyroDiagnosticForCurrentClip() }
                } label: {
                    if appState.isRunningGyroDiag {
                        ProgressView().controlSize(.small)
                    } else {
                        Text(isBatch && appState.gyroDiagResult == nil ? "Deep Check" : "Refresh")
                    }
                }
                .buttonStyle(.borderless)
                .font(.caption)
                .disabled(appState.selectedMP4URL == nil || appState.isRunningGyroDiag)
            }

            if let err = appState.gyroDiagError {
                Text(err)
                    .font(.caption)
                    .foregroundStyle(.red)
            } else {
                HStack(spacing: 8) {
                    if let gf = readyForGyroflow {
                        StudioStatusPill(
                            gf ? "Gyroflow Ready" : "Gyroflow Blocked",
                            systemImage: gf ? "checkmark.circle.fill" : "xmark.circle.fill",
                            color: gf ? .green : .red
                        )
                    }
                    if let cat = readyForCatalyst {
                        StudioStatusPill(
                            cat ? "Catalyst Ready" : "Catalyst Blocked",
                            systemImage: cat ? "checkmark.circle.fill" : "xmark.circle.fill",
                            color: cat ? .green : .orange
                        )
                    }
                }

                if let summary, !summary.isEmpty {
                    Text(summary)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                if !recommendedActions.isEmpty {
                    VStack(alignment: .leading, spacing: 3) {
                        ForEach(recommendedActions, id: \.self) { action in
                            Text("• \(action)")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                }
            }
        }
    }

    private func checkRow(title: String, passed: Bool, detail: String) -> some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: passed ? "checkmark.circle.fill" : "xmark.circle.fill")
                .font(.callout)
                .foregroundStyle(passed ? .green : .red)
                .padding(.top, 1)

            VStack(alignment: .leading, spacing: 1) {
                Text(title)
                    .font(.callout.weight(.medium))
                Text(detail)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Spacer()
        }
    }

    private func detailRow(_ label: String, _ value: String, monospaced: Bool = false) -> some View {
        VStack(alignment: .leading, spacing: 1) {
            Text(label)
                .font(.caption2)
                .foregroundStyle(.secondary)
            Text(value)
                .font(monospaced ? .caption2.monospaced() : .caption)
                .textSelection(.enabled)
        }
    }

    private func chooseXMLFile() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.xml]
        panel.allowsMultipleSelection = false
        panel.canChooseDirectories = false
        panel.message = "Select a Sony *M01.XML sidecar file"
        if panel.runModal() == .OK, let url = panel.url {
            Task { await appState.selectXMLFile(url) }
        }
    }
}
