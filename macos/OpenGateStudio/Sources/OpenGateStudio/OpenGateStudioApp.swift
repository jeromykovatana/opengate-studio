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
                .frame(minWidth: 940, minHeight: 660)
                .task {
                    await appState.bootstrapIfNeeded()
                }
        }
        .defaultSize(width: 1100, height: 760)
    }
}
