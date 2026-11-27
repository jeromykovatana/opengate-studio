import AppKit
import OpenGateStudioCore
import SwiftUI

public struct ContentView: View {
    @EnvironmentObject private var appState: AppState

    public init() {}

    public var body: some View {
        VStack(spacing: 0) {
            if let startupError = appState.startupError {
                startupBanner(startupError)
                Divider()
            }

            if let pinRes = appState.pinResult, !pinRes.ok {
                pinMismatchBanner
                Divider()
            }

            if appState.offlineMockCamera {
                simulationModeBanner
                Divider()
            }

            mainBody
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .background(Color(nsColor: .windowBackgroundColor))
        .toolbar {
            ToolbarItem(placement: .navigation) {
                cameraModelPicker
            }

            ToolbarItem(placement: .principal) {
                Picker("Workspace", selection: $appState.selectedDestination) {
                    ForEach(StudioDestination.allCases) { destination in
                        Text(destination.rawValue).tag(destination)
                    }
                }
                .pickerStyle(.segmented)
                .frame(width: 190)
            }

            ToolbarItemGroup(placement: .primaryAction) {
                modeAndIntegrityToolbarButton

                Button {
                    appState.showDiagnosticsSheet = true
                } label: {
                    Label("Diagnostics", systemImage: "wrench.and.screwdriver")
                }
                .help("Diagnostics, Console Log & Field Report")

                if appState.selectedDestination == .clips {
                    Button {
                        appState.isClipInspectorPresented.toggle()
                    } label: {
                        Label("Inspector", systemImage: "sidebar.trailing")
                    }
                    .help("Show or Hide Clip Inspector")
                }
            }
        }
        .sheet(item: $appState.activeLiveSession) { _ in
            LiveSessionSheetView()
                .environmentObject(appState)
        }
        .sheet(isPresented: $appState.showSetupGuideSheet) {
            CameraSetupWizardView()
                .environmentObject(appState)
        }
        .sheet(isPresented: $appState.showDiagnosticsSheet) {
            DiagnosticsSheetView()
                .environmentObject(appState)
        }
        .sheet(isPresented: $appState.showProxyExportSheet) {
            ProxyExportSheetView()
                .environmentObject(appState)
        }
        .sheet(isPresented: $appState.showGyroflowPresetsSheet) {
            GyroflowPresetsSheetView()
                .environmentObject(appState)
        }
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in
            Task {
                await appState.handleAppDidBecomeActive()
            }
        }
    }

    // MARK: - Toolbar Controls

    private var cameraModelPicker: some View {
        Picker("Camera", selection: $appState.selectedBodyId) {
            if appState.bodies.isEmpty {
                Text("ZV-E1 2.02").tag("zve1_202")
                Text("a7S III 5.01").tag("a7s3_501")
                Text("FX3 7.02").tag("fx3_702")
                Text("a7C 2.03").tag("a7c_203")
                Text("ZV-E10 2.03").tag("zve10_203")
            } else {
                ForEach(appState.bodies) { body in
                    Text(body.displayName).tag(body.bodyId)
                }
            }
        }
        .pickerStyle(.menu)
        .labelsHidden()
        .frame(width: 155)
        .disabled(appState.isLiveSessionActive)
        .help("Select Sony Camera Body & Firmware")
    }

    private var modeAndIntegrityToolbarButton: some View {
        let pinMismatch = (appState.pinResult != nil && !appState.pinsVerifiedForAllOrSelected)

        return Button {
            appState.showModePopover.toggle()
        } label: {
            HStack(spacing: 6) {
                if pinMismatch {
                    Image(systemName: "exclamationmark.shield.fill")
                        .foregroundStyle(.orange)
                } else if appState.offlineMockCamera {
                    Image(systemName: "desktopcomputer")
                        .foregroundStyle(.blue)
                } else {
                    Circle()
                        .fill(Color.green)
                        .frame(width: 7, height: 7)
                }

                Text(appState.offlineMockCamera ? "Simulation" : "Live USB")
                    .font(.callout.weight(.medium))
            }
        }
        .help("Camera Connection Mode & Kit Integrity")
        .popover(isPresented: $appState.showModePopover, arrowEdge: .bottom) {
            modeAndIntegrityPopover
        }
    }

    private var modeAndIntegrityPopover: some View {
        let verified = appState.pinsVerifiedForAllOrSelected

        return VStack(alignment: .leading, spacing: 14) {
            VStack(alignment: .leading, spacing: 8) {
                Text("Connection Mode")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)

                Toggle(isOn: $appState.offlineMockCamera) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Offline Simulation Mode")
                            .font(.callout.weight(.medium))
                        Text("Practice safely without a camera connected. Never unlocks Live USB.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
                .toggleStyle(.switch)
                .disabled(appState.isLiveSessionActive)

                if appState.offlineMockCamera {
                    HStack {
                        Text("Simulated State")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Spacer()
                        Picker("Simulated State", selection: $appState.mockState) {
                            ForEach(MockCameraState.allCases) { state in
                                Text(state.friendlyName).tag(state)
                            }
                        }
                        .labelsHidden()
                        .frame(width: 190)
                    }
                    .padding(.top, 2)
                }
            }

            Divider()

            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Text("Kit Integrity (SHA-256)")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.secondary)
                    Spacer()
                    StudioStatusPill(
                        verified ? "Verified" : "Issue Found",
                        systemImage: verified ? "checkmark.shield.fill" : "exclamationmark.shield.fill",
                        color: verified ? .green : .orange
                    )
                }

                if let pinRes = appState.pinResult {
                    Text("\(pinRes.checkedFiles) signed kit files checked.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                HStack(spacing: 8) {
                    Button {
                        Task { await appState.verifyPins() }
                    } label: {
                        if appState.isVerifyingPins {
                            ProgressView().controlSize(.small)
                        } else {
                            Text("Re-Verify")
                        }
                    }
                    .buttonStyle(.bordered)
                    .controlSize(.small)
                    .disabled(appState.isVerifyingPins)

                    Button("Inspect Details…") {
                        appState.showModePopover = false
                        appState.selectedDiagnosticsTab = .pins
                        appState.showDiagnosticsSheet = true
                    }
                    .buttonStyle(.borderless)
                    .font(.caption)

                    Spacer()
                }
            }

            if !appState.offlineMockCamera {
                Divider()
                HStack {
                    Button {
                        appState.showModePopover = false
                        Task { await appState.syncLatestCameraSession() }
                    } label: {
                        Label("Sync Latest Camera Session", systemImage: "arrow.triangle.2.circlepath")
                    }
                    .buttonStyle(.bordered)
                    .controlSize(.small)
                    .disabled(appState.isSyncingSession || appState.isLiveSessionActive)
                    Spacer()
                }
            }
        }
        .padding(16)
        .frame(width: 340)
    }

    // MARK: - Top Window Banners

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
        .padding(.vertical, 9)
        .background(Color.red.opacity(0.11))
    }

    private var pinMismatchBanner: some View {
        HStack(spacing: 10) {
            Image(systemName: "exclamationmark.shield.fill")
                .foregroundStyle(.orange)
            Text("Kit SHA-256 verification failed. Live USB operations are locked until kit files pass verification.")
                .font(.callout.weight(.medium))
            Spacer()
            Button("Inspect Pins…") {
                appState.selectedDiagnosticsTab = .pins
                appState.showDiagnosticsSheet = true
            }
            .buttonStyle(.bordered)
            .controlSize(.small)

            Button("Re-Verify") {
                Task { await appState.verifyPins() }
            }
            .buttonStyle(.borderedProminent)
            .tint(.orange)
            .controlSize(.small)
            .disabled(appState.isVerifyingPins)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 9)
        .background(Color.orange.opacity(0.12))
    }

    private var simulationModeBanner: some View {
        HStack(spacing: 12) {
            Image(systemName: "desktopcomputer")
                .font(.callout.weight(.semibold))
                .foregroundStyle(.blue)

            Text("Simulation Mode — Offline Mock Camera (Volatile RAM Only)")
                .font(.callout.weight(.medium))

            Spacer()

            Picker("State", selection: $appState.mockState) {
                ForEach(MockCameraState.allCases) { state in
                    Text(state.friendlyName).tag(state)
                }
            }
            .labelsHidden()
            .controlSize(.small)
            .frame(width: 195)

            Button("Switch to Live USB") {
                appState.offlineMockCamera = false
            }
            .buttonStyle(.bordered)
            .controlSize(.small)
            .disabled(appState.isLiveSessionActive)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 8)
        .background(Color.blue.opacity(0.10))
    }

    // MARK: - Main Workspace

    @ViewBuilder
    private var mainBody: some View {
        switch appState.selectedDestination {
        case .camera:
            CameraWorkspaceView()
        case .clips:
            ClipsWorkspaceView()
        }
    }
}
