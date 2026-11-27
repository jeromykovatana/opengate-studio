import AppKit
import OpenGateStudioCore
import SwiftUI

public struct GyroflowPresetsSheetView: View {
    @EnvironmentObject private var appState: AppState
    @Environment(\.dismiss) private var dismiss
    @State private var showTechnicalDetails: Bool = false

    public init() {}

    public var body: some View {
        VStack(spacing: 0) {
            sheetHeader
            Divider()

            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    if let err = appState.gyroPresetError {
                        StudioCallout(
                            icon: "exclamationmark.triangle.fill",
                            color: .red,
                            title: "Gyroflow Preset Error",
                            detail: err
                        )
                    }

                    if appState.isLoadingGyroPresets {
                        StudioSurface(padding: 16) {
                            HStack(spacing: 10) {
                                ProgressView().controlSize(.small)
                                Text("Loading bundled 3:2 Sony lens profiles…")
                                    .font(.callout)
                                    .foregroundStyle(.secondary)
                            }
                        }
                    } else if let list = appState.gyroPresetList {
                        StudioSurface(padding: 14) {
                            VStack(alignment: .leading, spacing: 10) {
                                ForEach(Array(list.presets.enumerated()), id: \.element.id) { idx, preset in
                                    if idx > 0 { Divider() }
                                    presetRow(preset)
                                }
                            }
                        }

                        DisclosureGroup("Technical Details", isExpanded: $showTechnicalDetails) {
                            VStack(alignment: .leading, spacing: 6) {
                                ForEach(list.presets) { preset in
                                    Text("\(preset.filename)  ·  \(preset.evidenceLevel)  ·  sha256: \(String(preset.sha256.prefix(12)))…")
                                        .font(.caption2.monospaced())
                                        .foregroundStyle(.secondary)
                                        .textSelection(.enabled)
                                }
                            }
                            .padding(.top, 6)
                        }
                        .font(.caption.weight(.medium))
                        .foregroundStyle(.secondary)
                    }

                    if let installed = appState.gyroPresetInstallResult {
                        StudioSurface(accent: .green, padding: 14) {
                            HStack(spacing: 12) {
                                Image(systemName: "checkmark.seal.fill")
                                    .font(.title3)
                                    .foregroundStyle(.green)

                                VStack(alignment: .leading, spacing: 2) {
                                    Text("Installed \(installed.installedCount) Gyroflow profile(s)")
                                        .font(.callout.weight(.semibold))
                                        .foregroundStyle(.green)
                                    Text(installed.targetDir)
                                        .font(.caption.monospaced())
                                        .foregroundStyle(.secondary)
                                        .textSelection(.enabled)
                                }

                                Spacer()

                                Button("Reveal Folder") {
                                    NSWorkspace.shared.selectFile(nil, inFileViewerRootedAtPath: installed.targetDir)
                                }
                                .buttonStyle(.bordered)
                                .controlSize(.small)
                            }
                        }
                    }
                }
                .padding(20)
            }

            Divider()
            sheetFooter
        }
        .frame(minWidth: 520, idealWidth: 560, minHeight: 400, idealHeight: 470)
        .task {
            if appState.gyroPresetList == nil && !appState.isLoadingGyroPresets {
                await appState.loadGyroflowPresets()
            }
        }
    }

    private var sheetHeader: some View {
        HStack(spacing: 12) {
            Image(systemName: "gyroscope")
                .font(.title2)
                .foregroundStyle(.teal)
                .frame(width: 34, height: 34)
                .background(Color.teal.opacity(0.14))
                .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))

            VStack(alignment: .leading, spacing: 2) {
                Text("Gyroflow 3:2 Lens Profiles")
                    .font(.headline)
                Text("Install calibrated open-gate camera readout profiles for Gyroflow.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Spacer()
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 14)
        .background(.bar)
    }

    private func presetRow(_ preset: GyroflowPresetEntry) -> some View {
        let isMeasured = preset.evidenceLevel == "hardware_measured"
        return HStack(spacing: 12) {
            Image(systemName: "camera.metering.center.weighted")
                .font(.title3)
                .foregroundStyle(.blue)

            VStack(alignment: .leading, spacing: 2) {
                Text(preset.cameraModel.isEmpty ? preset.filename : preset.cameraModel)
                    .font(.callout.weight(.semibold))
                Text("\(preset.dimension)  ·  Readout: \(preset.frameReadoutTimeMs.map { String(format: "%.2f ms", $0) } ?? "—")")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Spacer()

            StudioStatusPill(
                isMeasured ? "Measured" : "Estimated",
                color: isMeasured ? .green : .orange
            )
        }
    }

    private var sheetFooter: some View {
        HStack(spacing: 10) {
            Button("Close") {
                dismiss()
            }
            .keyboardShortcut(.cancelAction)

            Button {
                Task { await appState.loadGyroflowPresets() }
            } label: {
                Label("Refresh", systemImage: "arrow.clockwise")
            }
            .buttonStyle(.bordered)
            .disabled(appState.isLoadingGyroPresets)

            Spacer()

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
            .disabled(appState.isInstallingGyroPresets)
            .keyboardShortcut(.defaultAction)
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 14)
        .background(.bar)
    }
}
