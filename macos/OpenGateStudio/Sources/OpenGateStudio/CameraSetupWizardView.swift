import OpenGateStudioCore
import SwiftUI

public struct CameraSetupWizardView: View {
    @EnvironmentObject private var appState: AppState
    @Environment(\.dismiss) private var dismiss

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
            appState.checkedAppsClosed,
        ].filter { $0 }.count
    }

    public var body: some View {
        VStack(spacing: 0) {
            sheetHeader
            Divider()

            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    firmwareAndCardSection
                    menuAndMacSection
                    shootingAndSafetySection
                }
                .padding(20)
            }

            Divider()
            sheetFooter
        }
        .frame(minWidth: 580, idealWidth: 630, minHeight: 520, idealHeight: 610)
    }

    // MARK: - Header & Footer

    private var sheetHeader: some View {
        HStack(spacing: 12) {
            Image(systemName: "checklist")
                .font(.title2)
                .foregroundStyle(.blue)
                .frame(width: 34, height: 34)
                .background(Color.blue.opacity(0.12))
                .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))

            VStack(alignment: .leading, spacing: 2) {
                Text("Camera Setup Guide — \(profile.displayName)")
                    .font(.headline)
                Text("Volatile RAM only: nothing is flashed to camera eMMC or written to your SD card.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Spacer()

            StudioStatusPill(
                "\(checkedCount) of 5 Checked",
                systemImage: appState.isSetupWizardChecklistComplete ? "checkmark.circle.fill" : "circle.dashed",
                color: appState.isSetupWizardChecklistComplete ? .green : .blue
            )
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 14)
        .background(.bar)
    }

    private var sheetFooter: some View {
        HStack(spacing: 12) {
            Button("Try Offline Simulation") {
                appState.offlineMockCamera = true
                dismiss()
            }
            .buttonStyle(.bordered)

            Spacer()

            Button("Done") {
                dismiss()
            }
            .buttonStyle(.borderedProminent)
            .keyboardShortcut(.defaultAction)
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 14)
        .background(.bar)
    }

    // MARK: - Sections

    private var firmwareAndCardSection: some View {
        let done = appState.checkedFirmwareVersion && appState.checkedSdCardSlot1
        return setupSection(number: 1, title: "Firmware & SD Card", isDone: done) {
            VStack(alignment: .leading, spacing: 12) {
                StudioCallout(
                    icon: "sdcard.fill",
                    color: .blue,
                    title: "No files need to be copied onto your SD card",
                    detail: "Leave a normal formatted SD or CFexpress card in Slot 1 so the camera mounts as USB Mass Storage. Nothing is erased or modified."
                )

                HStack(spacing: 8) {
                    Text("MENU > Setup > Setup Option > Version")
                        .font(.caption.monospaced())
                        .foregroundStyle(.secondary)
                    Spacer()
                    StudioStatusPill(
                        profile.firmwareBadge,
                        color: profile.isFX3 ? .orange : .green
                    )
                }

                if let caution = profile.firmwareCaution {
                    StudioCallout(
                        icon: "exclamationmark.triangle.fill",
                        color: .orange,
                        title: "Verify Exact FX3 Hardware Model",
                        detail: caution
                    )
                }

                Divider()

                Toggle(
                    "Confirmed exact camera firmware version (\(profile.firmwareBadge))",
                    isOn: $appState.checkedFirmwareVersion
                )
                .font(.callout)

                Toggle(
                    "Normal formatted SD/CFexpress card is inserted in Slot 1",
                    isOn: $appState.checkedSdCardSlot1
                )
                .font(.callout)
            }
        }
    }

    private var menuAndMacSection: some View {
        let done = appState.checkedUsbMassStorage && appState.checkedMovie24pSettings && appState.checkedAppsClosed
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
            return parts.joined(separator: " · ")
        }()

        return setupSection(number: 2, title: "Camera Menu & Mac Prep", isDone: done) {
            VStack(alignment: .leading, spacing: 11) {
                Toggle(isOn: $appState.checkedUsbMassStorage) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("USB Connection Mode = Mass Storage (if prompted on plug-in, tap Image Transfer (MSC))")
                            .font(.callout.weight(.medium))
                        Text("USB Power Supply = Off · Smartphone Connection / Cnct. while Power OFF = Off")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }

                Toggle(isOn: $appState.checkedMovie24pSettings) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Configure Movie Mode preset before cold boot & Stills switch:")
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
                        Text("Prevents macOS media apps from grabbing USB Mass Storage during preflight or apply.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            }
        }
    }

    private var shootingAndSafetySection: some View {
        let done = appState.batteryPulled10s && appState.cameraInStillsMode
        return setupSection(number: 3, title: "Power, Stills Mode & Safety Rules", isDone: done) {
            VStack(alignment: .leading, spacing: 11) {
                StudioCallout(
                    icon: "camera.fill",
                    color: .blue,
                    title: profile.stillsModeTitle,
                    detail: "\(profile.stillsModeInstruction) Pull battery for >= 10 seconds, boot straight into Stills mode, and do NOT enter Movie mode before clicking Apply."
                )

                StudioCallout(
                    icon: "exclamationmark.triangle.fill",
                    color: .orange,
                    title: "24p / 25p / 30p Only While Open-Gate Is Active",
                    detail: "23.98p (24p), 25p (PAL), and 29.97p (30p) are supported. Switching to 50p, 60p, or 120p while Open-Gate is active distorts or crashes the camera."
                )

                if profile.isFX3 {
                    StudioCallout(
                        icon: "hand.raised.fill",
                        color: .red,
                        title: "FX3 Playback Freeze Warning",
                        detail: "Do NOT press Playback on open-gate clips on FX3 without the experimental Playback Fix pack. If Playback shows Unable to Display, do NOT retry — retrying freezes the camera until a battery pull."
                    )

                    StudioCallout(
                        icon: "info.circle.fill",
                        color: .blue,
                        title: "FX3 Field Note (NTSC / PAL & Mode Switch)",
                        detail: "NTSC (23.98p / 29.97p) and PAL (25p) are supported automatically. If switching Stills -> Movie after Apply flickers on edge setups, booting cold in Movie mode may help (Apply still starts in Stills)."
                    )
                }

                StudioCallout(
                    icon: "battery.25",
                    color: profile.isPowerSwitchResetBody ? .red : .orange,
                    title: profile.isPowerSwitchResetBody
                        ? "10s Battery Pull Reset Rule (ZV-E1 & a7S III)"
                        : "10s Battery Pull Reset Rule",
                    detail: "Flipping only the power switch can leave partial patch state active (blocking Apply). Always pull the battery for >= 10 seconds to restore stock RAM."
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

    // MARK: - Section Container

    private func setupSection<Content: View>(
        number: Int,
        title: String,
        isDone: Bool,
        @ViewBuilder content: @escaping () -> Content
    ) -> some View {
        let accent: Color = isDone ? .green : .blue
        return StudioSurface(accent: isDone ? .green : nil, padding: 15) {
            VStack(alignment: .leading, spacing: 12) {
                HStack(spacing: 8) {
                    Text("\(number)")
                        .font(.caption.weight(.bold))
                        .frame(width: 20, height: 20)
                        .background(accent.opacity(0.16))
                        .foregroundStyle(accent)
                        .clipShape(Circle())

                    Text(title)
                        .font(.headline)

                    Spacer()

                    if isDone {
                        StudioStatusPill("Checked", systemImage: "checkmark.circle.fill", color: .green)
                    }
                }

                content()
            }
        }
    }
}
