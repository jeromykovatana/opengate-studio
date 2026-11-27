import AppKit
import SwiftUI

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }
}

@main
struct OpenGateStudioApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @StateObject private var appState = AppState()

    var body: some Scene {
        WindowGroup("OpenGate Studio") {
            ContentView()
                .environmentObject(appState)
                .frame(minWidth: 880, minHeight: 620)
                .task {
                    await appState.bootstrapIfNeeded()
                }
        }
        .defaultSize(width: 1040, height: 720)
        .commands {
            CommandMenu("Camera") {
                Button("Camera Setup Guide…") {
                    appState.showSetupGuideSheet = true
                }
                .keyboardShortcut("g", modifiers: [.command, .shift])

                Button("Verify Kit Integrity") {
                    Task { await appState.verifyPins() }
                }
                .keyboardShortcut("v", modifiers: [.command, .shift])
                .disabled(appState.isVerifyingPins)

                Button("Sync Latest Camera Session") {
                    Task { await appState.syncLatestCameraSession() }
                }
                .keyboardShortcut("r", modifiers: [.command])
                .disabled(appState.offlineMockCamera || appState.isSyncingSession || appState.isLiveSessionActive)

                Divider()

                Toggle("Offline Simulation Mode", isOn: $appState.offlineMockCamera)
                    .keyboardShortcut("s", modifiers: [.command, .option])
                    .disabled(appState.isLiveSessionActive)
            }

            CommandGroup(after: .toolbar) {
                Button(appState.isClipInspectorPresented ? "Hide Clip Inspector" : "Show Clip Inspector") {
                    appState.isClipInspectorPresented.toggle()
                }
                .keyboardShortcut("i", modifiers: [.command, .option])
                .disabled(appState.selectedDestination != .clips)

                Divider()

                Button("Diagnostics & Console…") {
                    appState.selectedDiagnosticsTab = .console
                    appState.showDiagnosticsSheet = true
                }
                .keyboardShortcut("d", modifiers: [.command, .option])

                Button("Field Test Report…") {
                    appState.selectedDiagnosticsTab = .fieldReport
                    appState.showDiagnosticsSheet = true
                }
            }
        }
    }
}
