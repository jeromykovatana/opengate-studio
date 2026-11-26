import OpenGateStudioCore
import SwiftUI

private struct BodySetupProfile {
    let bodyId: String
    let displayName: String
    let firmwareBadge: String
    let firmwareCaution: String?
    let bodySpecificMovieSetting: String?
    let stillsModeTitle: String
    let stillsModeInstruction: String
    let isFX3: Bool
    let isPowerSwitchResetBody: Bool

    static func forBody(id: String, bodyInfo: BodyInfo?) -> BodySetupProfile {
        switch id {
        case "a7s3_501":
            return BodySetupProfile(
                bodyId: id,
                displayName: bodyInfo?.displayName ?? "a7S III 5.01",
                firmwareBadge: "a7S III -> Ver. 5.01",
                firmwareCaution: nil,
                bodySpecificMovieSetting: nil,
                stillsModeTitle: "Mode Dial -> Stills",
                stillsModeInstruction: "Turn the top mode dial to a Stills position (M / S / A / P) before booting.",
                isFX3: false,
                isPowerSwitchResetBody: true
            )
        case "fx3_702":
            return BodySetupProfile(
                bodyId: id,
                displayName: bodyInfo?.displayName ?? "FX3 7.02",
                firmwareBadge: "FX3 -> Ver. 7.02 (verify ILME-FX3, NOT ILME-FX3A)",
                firmwareCaution: "Verify Model Name is ILME-FX3 (NOT ILME-FX3A) in MENU > Setup > Setup Option > Version.",
                bodySpecificMovieSetting: "De-Squeeze Display = Off",
                stillsModeTitle: "MODE Button -> Stills",
                stillsModeInstruction: "Press the MODE button and select Stills before connecting USB.",
                isFX3: true,
                isPowerSwitchResetBody: false
            )
        default:
            return BodySetupProfile(
                bodyId: id,
                displayName: bodyInfo?.displayName ?? "ZV-E1 2.02",
                firmwareBadge: "ZV-E1 -> Ver. 2.02",
                firmwareCaution: nil,
                bodySpecificMovieSetting: "Auto Framing = Off",
                stillsModeTitle: "Still/Movie/S&Q Button -> Still",
                stillsModeInstruction: "Press the top Still/Movie/S&Q button until the camera is in Stills mode.",
                isFX3: false,
                isPowerSwitchResetBody: true
            )
        }
    }
}

public struct CameraSetupWizardView: View {
    @EnvironmentObject private var appState: AppState

    public init() {}

    private var profile: BodySetupProfile {
        BodySetupProfile.forBody(id: appState.selectedBodyId, bodyInfo: appState.selectedBody)
    }

    private var checkedCount: Int {
        [
            appState.checkedFirmwareVersion,
            appState.checkedSdCardSlot1,
            appState.checkedUsbMassStorage,
            appState.checkedMovie24pSettings,
            appState.checkedAppsClosed
        ].filter { $0 }.count
    }

    public var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                headerBanner
                step1Card
                step2Card
                step3Card
                actionFooter
            }
            .padding(20)
        }
    }

    // MARK: - Header Banner

    private var headerBanner: some View {
        HStack(alignment: .center, spacing: 14) {
            Image(systemName: "checklist")
                .font(.title)
                .foregroundStyle(.blue)
                .frame(width: 36, height: 36)

            VStack(alignment: .leading, spacing: 3) {
                Text("Pre-Flight Camera Setup Wizard — \(profile.displayName)")
                    .font(.title3.weight(.semibold))
                Text("Volatile RAM patches only: nothing is flashed to camera eMMC or written to your SD card. Pull battery >= 10s anytime to restore stock.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Spacer()

            HStack(spacing: 6) {
                Image(systemName: appState.isSetupWizardChecklistComplete ? "checkmark.circle.fill" : "circle.dashed")
                Text("\(checkedCount) / 5 Checked")
            }
            .font(.caption.weight(.semibold))
            .padding(.horizontal, 10)
            .padding(.vertical, 5)
            .background(appState.isSetupWizardChecklistComplete ? Color.green.opacity(0.16) : Color.blue.opacity(0.14))
            .foregroundStyle(appState.isSetupWizardChecklistComplete ? Color.green : Color.blue)
            .clipShape(Capsule())
        }
        .padding(14)
        .background(
            RoundedRectangle(cornerRadius: 10)
                .fill(Color(nsColor: .controlBackgroundColor))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 10)
                .stroke(Color.blue.opacity(0.25), lineWidth: 1)
        )
    }

    // MARK: - Step 1: Firmware & SD Card Rules

    private var step1Card: some View {
        stepCard(
            number: 1,
            title: "Firmware & SD Card Rules",
            isDone: appState.checkedFirmwareVersion && appState.checkedSdCardSlot1
        ) {
            VStack(alignment: .leading, spacing: 12) {
                HStack(alignment: .top, spacing: 10) {
                    Image(systemName: "sdcard.fill")
                        .font(.title3)
                        .foregroundStyle(.blue)
                    VStack(alignment: .leading, spacing: 3) {
                        Text("No files need to be copied onto your SD card.")
                            .font(.callout.weight(.bold))
                        Text("Just leave a normal formatted SD/CFexpress card in Slot 1 (needed so the camera mounts as USB Mass Storage; nothing is erased).")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
                .padding(12)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(Color.blue.opacity(0.08))
                .overlay(
                    RoundedRectangle(cornerRadius: 8)
                        .stroke(Color.blue.opacity(0.32), lineWidth: 1)
                )
                .clipShape(RoundedRectangle(cornerRadius: 8))

                VStack(alignment: .leading, spacing: 6) {
                    HStack(spacing: 8) {
                        Text("MENU > Setup > Setup Option > Version")
                            .font(.caption.monospaced())
                            .foregroundStyle(.secondary)
                        Spacer()
                        Text(profile.firmwareBadge)
                            .font(.caption.monospaced().weight(.bold))
                            .padding(.horizontal, 10)
                            .padding(.vertical, 4)
                            .background(profile.isFX3 ? Color.orange.opacity(0.18) : Color.green.opacity(0.16))
                            .foregroundStyle(profile.isFX3 ? Color.orange : Color.green)
                            .clipShape(Capsule())
                    }

                    if let caution = profile.firmwareCaution {
                        Label(caution, systemImage: "exclamationmark.triangle.fill")
                            .font(.caption.weight(.medium))
                            .foregroundStyle(.orange)
                    }

                    Text("Supported firmware badges: ZV-E1 -> Ver. 2.02  |  a7S III -> Ver. 5.01  |  FX3 -> Ver. 7.02 (verify ILME-FX3, NOT ILME-FX3A)")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }

                Divider()

                Toggle(
                    "Confirmed exact camera firmware version (\(profile.firmwareBadge))",
                    isOn: $appState.checkedFirmwareVersion
                )
                .font(.callout)

                Toggle(
                    "Normal formatted SD/CFexpress card is inserted in Slot 1 (no files copied)",
                    isOn: $appState.checkedSdCardSlot1
                )
                .font(.callout)
            }
        }
    }

    // MARK: - Step 2: Exact Camera Menu Settings

    private var step2Card: some View {
        let moviePresetSummary: String = {
            var parts = [
                "XAVC HS 4K or XAVC S 4K",
                "24p (23.98p), 25p (PAL), or 30p (29.97p)",
                "APS-C / Super 35 = Off",
                "S&Q = Off",
                "Proxy Recording = Off"
            ]
            if let bodySpecific = profile.bodySpecificMovieSetting {
                parts.append(bodySpecific)
            }
            return parts.joined(separator: "  •  ")
        }()

        return stepCard(
            number: 2,
            title: "Exact Camera Menu Settings & Mac Cleanup",
            isDone: appState.checkedUsbMassStorage && appState.checkedMovie24pSettings && appState.checkedAppsClosed
        ) {
            VStack(alignment: .leading, spacing: 10) {
                Toggle(isOn: $appState.checkedUsbMassStorage) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("USB Connection Mode = Mass Storage (if prompted on plug-in, tap Image Transfer (MSC))")
                            .font(.callout.weight(.medium))
                        Text("USB Power Supply = Off   ·   Smartphone Connection / Cnct. while Power OFF = Off")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }

                Toggle(isOn: $appState.checkedMovie24pSettings) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Movie Mode preset (configure BEFORE cold boot & Stills switch):")
                            .font(.callout.weight(.medium))
                        Text(moviePresetSummary)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }

                Toggle(isOn: $appState.checkedAppsClosed) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Close Photos, Image Capture, and Finder card windows on Mac")
                            .font(.callout.weight(.medium))
                        Text("Prevents macOS media apps from re-grabbing USB Mass Storage during preflight/apply.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            }
        }
    }

    // MARK: - Step 3: Power, Stills Mode & Safety Rules

    private var step3Card: some View {
        stepCard(
            number: 3,
            title: "Power, Stills Mode & Critical Safety Rules",
            isDone: appState.batteryPulled10s && appState.cameraInStillsMode
        ) {
            VStack(alignment: .leading, spacing: 12) {
                VStack(alignment: .leading, spacing: 6) {
                    HStack(spacing: 8) {
                        Label(profile.stillsModeTitle, systemImage: "camera.fill")
                            .font(.callout.weight(.semibold))
                        Spacer()
                        Text("Stills before Apply")
                            .font(.caption2.weight(.bold))
                            .padding(.horizontal, 8)
                            .padding(.vertical, 3)
                            .background(Color.blue.opacity(0.14))
                            .foregroundStyle(.blue)
                            .clipShape(Capsule())
                    }
                    Text(profile.stillsModeInstruction)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Text("Pull battery for >= 10 seconds, boot straight into Stills mode, and do NOT enter Movie mode before clicking Apply.")
                        .font(.caption.weight(.medium))
                }
                .padding(10)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(Color(nsColor: .textBackgroundColor).opacity(0.6))
                .clipShape(RoundedRectangle(cornerRadius: 8))

                // 24p / 25p / 30p rule
                warningCallout(
                    icon: "exclamationmark.triangle.fill",
                    color: .orange,
                    title: "24p / 25p / 30p Only While Open-Gate Is Applied",
                    detail: "23.98p (24p), 25p (PAL), and 29.97p (30p) are supported. Switching to 50p, 60p, or 120p while open-gate is applied distorts or crashes the camera."
                )

                // FX3 Playback Freeze Warning & Field Note (prominent on FX3)
                if profile.isFX3 {
                    warningCallout(
                        icon: "hand.raised.fill",
                        color: .red,
                        title: "FX3 Playback Freeze Warning",
                        detail: "Do NOT press Playback on open-gate clips on FX3 without P29 (fx3_playback). If Playback shows Unable to Display, do NOT retry — retrying freezes the camera until a battery pull."
                    )

                    warningCallout(
                        icon: "info.circle.fill",
                        color: .blue,
                        title: "FX3 Field Note (NTSC 24p/30p, PAL 25p & Mode Switch)",
                        detail: "NTSC (23.98p / 29.97p on 0x8c0) and PAL (25p on 0x820) are both supported automatically via dual NTSC/PAL MULTI_REC in L5/L6. If switching Stills -> Movie after Apply flickers or restarts on FX3, booting cold in Movie mode may still help on edge setups (apply still starts in Stills)."
                    )
                }

                // 10s Battery Pull Reset Warning (highlighted for ZV-E1 & a7S III)
                warningCallout(
                    icon: "battery.25",
                    color: profile.isPowerSwitchResetBody ? .red : .orange,
                    title: profile.isPowerSwitchResetBody
                        ? "10s Battery Pull Reset Warning (ZV-E1 & a7S III)"
                        : "10s Battery Pull Reset Rule",
                    detail: "Flipping only the power switch leaves half the patch active (mixed_powerswitch), which blocks Apply. Always pull the battery for >= 10 seconds to restore stock RAM."
                )

                // Field Re-Activation & False Color / Scopes note
                warningCallout(
                    icon: "arrow.clockwise.circle.fill",
                    color: .blue,
                    title: "Field Re-Activation & False Color / Scopes",
                    detail: "Powering off or swapping batteries clears volatile RAM; use the 'Safe Daily 3:2' preset in Step 2 for the fastest re-apply over USB-C. None of these firmware builds include in-body False Color DSP — use Sony Monitor & Control or an external monitor via hdmi32 for False Color / Waveform."
                )

                Divider()

                Toggle(
                    "I pulled the battery for >= 10 seconds and booted straight into Stills mode",
                    isOn: $appState.batteryPulled10s
                )
                .font(.callout)

                Toggle(
                    "Camera is currently in Stills mode (have NOT entered Movie mode yet)",
                    isOn: $appState.cameraInStillsMode
                )
                .font(.callout)
            }
        }
    }

    // MARK: - Action Footer

    private var actionFooter: some View {
        let readyForLive = appState.isSetupWizardChecklistComplete && appState.isChecklistComplete
        return HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 6) {
                    Image(systemName: readyForLive ? "checkmark.circle.fill" : "cable.connector")
                        .foregroundStyle(readyForLive ? .green : .accentColor)
                    Text(readyForLive ? "Setup Confirmed — Ready for Step 2: Apply & Packs" : "Proceed to Step 2: Apply & Packs")
                        .font(.headline)
                }
                Text("Runs natively in OpenGate Studio with macOS administrator approval — no Terminal required. Gate 1 checks stay editable anytime.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Spacer()

            Button {
                appState.offlineMockCamera = true
                appState.selectedTab = .packsAndSafety
            } label: {
                Text("Preview in Offline Mock")
            }
            .buttonStyle(.bordered)
            .controlSize(.large)

            Button {
                appState.offlineMockCamera = false
                appState.selectedTab = .packsAndSafety
            } label: {
                Label(
                    appState.isSetupWizardChecklistComplete
                        ? "Continue to Apply & Packs ->"
                        : "Use Real Camera (Live USB) ->",
                    systemImage: appState.isSetupWizardChecklistComplete ? "arrow.right.circle.fill" : "cable.connector"
                )
            }
            .buttonStyle(.borderedProminent)
            .tint(readyForLive ? .green : .accentColor)
            .controlSize(.large)
        }
        .padding(16)
        .background(
            RoundedRectangle(cornerRadius: 10)
                .fill(Color(nsColor: .controlBackgroundColor))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 10)
                .stroke(readyForLive ? Color.green.opacity(0.45) : Color.accentColor.opacity(0.30), lineWidth: 1)
        )
    }

    // MARK: - Helpers

    private func stepCard<Content: View>(
        number: Int,
        title: String,
        isDone: Bool,
        @ViewBuilder content: () -> Content
    ) -> some View {
        let accent: Color = isDone ? .green : .blue
        return VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("Step \(number)")
                    .font(.caption.weight(.bold))
                    .padding(.horizontal, 8)
                    .padding(.vertical, 3)
                    .background(accent.opacity(0.16))
                    .foregroundStyle(accent)
                    .clipShape(Capsule())

                Text(title)
                    .font(.headline)

                Spacer()

                Label(isDone ? "Checked" : "Review", systemImage: isDone ? "checkmark.circle.fill" : "circle")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(accent)
            }

            content()
        }
        .padding(14)
        .background(
            RoundedRectangle(cornerRadius: 10)
                .fill(Color(nsColor: .controlBackgroundColor))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 10)
                .stroke(accent.opacity(0.28), lineWidth: 1)
        )
    }

    private func warningCallout(icon: String, color: Color, title: String, detail: String) -> some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: icon)
                .font(.title3)
                .foregroundStyle(color)
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(.callout.weight(.bold))
                    .foregroundStyle(color)
                Text(detail)
                    .font(.caption)
            }
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(color.opacity(0.10))
        .overlay(
            RoundedRectangle(cornerRadius: 8)
                .stroke(color.opacity(0.38), lineWidth: 1)
        )
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }
}
