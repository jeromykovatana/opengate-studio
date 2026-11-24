import AppKit
import OpenGateStudioCore
import SwiftUI

public struct ContentView: View {
    @EnvironmentObject private var appState: AppState

    public init() {}

    public var body: some View {
        VStack(spacing: 0) {
            topBar
            Divider()
            if let startupError = appState.startupError {
                startupBanner(startupError)
            }
            mainBody
        }
        .background(Color(nsColor: .windowBackgroundColor))
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in
            Task {
                await appState.handleAppDidBecomeActive()
            }
        }
    }

    private var topBar: some View {
        VStack(spacing: 10) {
            HStack(spacing: 14) {
                HStack(spacing: 8) {
                    Image(systemName: "camera.aperture")
                        .font(.title2)
                        .foregroundStyle(.blue)
                    VStack(alignment: .leading, spacing: 1) {
                        Text("OpenGate Studio")
                            .font(.headline)
                        Text("Volatile RAM Open-Gate Controller")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }

                Spacer()

                // Camera Picker
                HStack(spacing: 6) {
                    Text("Camera")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Picker("Camera", selection: $appState.selectedBodyId) {
                        if appState.bodies.isEmpty {
                            Text("ZV-E1 2.02").tag("zve1_202")
                            Text("a7S III 5.01").tag("a7s3_501")
                            Text("FX3 7.02").tag("fx3_702")
                        } else {
                            ForEach(appState.bodies) { body in
                                Text(body.displayName).tag(body.bodyId)
                            }
                        }
                    }
                    .labelsHidden()
                    .frame(width: 160)
                }

                // SHA-256 Pin Verification Pill + Button
                HStack(spacing: 6) {
                    pinStatusPill
                    Button {
                        Task { await appState.verifyPins() }
                    } label: {
                        if appState.isVerifyingPins {
                            ProgressView()
                                .controlSize(.small)
                        } else {
                            Text("Verify Pins")
                        }
                    }
                    .buttonStyle(.bordered)
                    .disabled(appState.isVerifyingPins)
                }

                Divider()
                    .frame(height: 22)

                // Offline Mock Camera Toggle + Mock State Picker
                HStack(spacing: 8) {
                    Toggle("Offline Mock Camera", isOn: $appState.offlineMockCamera)
                        .toggleStyle(.switch)
                        .controlSize(.small)

                    if appState.offlineMockCamera {
                        Picker("Mock State", selection: $appState.mockState) {
                            ForEach(MockCameraState.allCases) { state in
                                Text(state.displayName).tag(state)
                            }
                        }
                        .labelsHidden()
                        .frame(width: 155)
                    }
                }
            }

            HStack {
                Picker("Workspace", selection: $appState.selectedTab) {
                    ForEach(StudioTab.allCases) { tab in
                        Text(tab.rawValue).tag(tab)
                    }
                }
                .pickerStyle(.segmented)
                .frame(maxWidth: 520)

                Spacer()

                safetyStatusSummaryBadge
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
        .background(.bar)
    }

    @ViewBuilder
    private var pinStatusPill: some View {
        let verified = appState.pinsVerifiedForAllOrSelected
        HStack(spacing: 5) {
            Image(systemName: verified ? "checkmark.shield.fill" : "exclamationmark.shield.fill")
            if let pinRes = appState.pinResult {
                Text(verified ? "Verified (\(pinRes.checkedFiles))" : "Pin Mismatch")
            } else {
                Text(verified ? "Verified" : "Unverified")
            }
        }
        .font(.caption.weight(.semibold))
        .padding(.horizontal, 10)
        .padding(.vertical, 5)
        .background(verified ? Color.green.opacity(0.16) : Color.orange.opacity(0.18))
        .foregroundStyle(verified ? Color.green : Color.orange)
        .clipShape(Capsule())
    }

    @ViewBuilder
    private var safetyStatusSummaryBadge: some View {
        HStack(spacing: 6) {
            Image(systemName: appState.offlineMockCamera ? "desktopcomputer" : "terminal.fill")
                .foregroundStyle(appState.offlineMockCamera ? .blue : .orange)
            Text(
                appState.offlineMockCamera
                    ? "Mock Simulation (\(appState.mockState.displayName)) — Volatile RAM Only"
                    : (appState.lastResultSource == .liveTerminal
                        ? "Live USB Mode — Synced from Terminal.app"
                        : "Live USB Mode — Interactive Terminal.app")
            )
            .font(.caption)
            .foregroundStyle(.secondary)
        }
    }

    private func startupBanner(_ error: String) -> some View {
        HStack(spacing: 10) {
            Image(systemName: "exclamationmark.triangle.fill")
                .foregroundStyle(.red)
            Text(error)
                .font(.callout)
                .lineLimit(2)
            Spacer()
            Button("Retry") {
                Task { await appState.retryLocateBridge() }
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.small)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
        .background(Color.red.opacity(0.12))
    }

    @ViewBuilder
    private var mainBody: some View {
        switch appState.selectedTab {
        case .packsAndSafety:
            FeaturePacksAndStepperView()
        case .clipInspector:
            ClipInspectorView()
        }
    }
}
