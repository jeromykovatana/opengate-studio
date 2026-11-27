import AppKit
import OpenGateStudioCore
import SwiftUI

// MARK: - Shared Surfaces & Badges

public struct StudioSurface<Content: View>: View {
    private let accent: Color?
    private let cornerRadius: CGFloat
    private let padding: CGFloat
    @ViewBuilder private let content: () -> Content

    public init(
        accent: Color? = nil,
        cornerRadius: CGFloat = 12,
        padding: CGFloat = 16,
        @ViewBuilder content: @escaping () -> Content
    ) {
        self.accent = accent
        self.cornerRadius = cornerRadius
        self.padding = padding
        self.content = content
    }

    public var body: some View {
        content()
            .padding(padding)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(
                RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                    .fill(Color(nsColor: .controlBackgroundColor))
            )
            .overlay(
                RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                    .strokeBorder(
                        accent?.opacity(0.32) ?? Color.primary.opacity(0.08),
                        lineWidth: 1
                    )
            )
    }
}

public struct StudioStatusPill: View {
    private let text: String
    private let systemImage: String?
    private let color: Color

    public init(_ text: String, systemImage: String? = nil, color: Color = .secondary) {
        self.text = text
        self.systemImage = systemImage
        self.color = color
    }

    public var body: some View {
        HStack(spacing: 4) {
            if let systemImage {
                Image(systemName: systemImage)
            }
            Text(text)
        }
        .font(.caption.weight(.semibold))
        .padding(.horizontal, 9)
        .padding(.vertical, 3.5)
        .background(color.opacity(0.14))
        .foregroundStyle(color)
        .clipShape(Capsule())
    }
}

public struct StudioCallout: View {
    private let icon: String
    private let color: Color
    private let title: String
    private let detail: String

    public init(icon: String, color: Color, title: String, detail: String) {
        self.icon = icon
        self.color = color
        self.title = title
        self.detail = detail
    }

    public var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: icon)
                .font(.callout.weight(.semibold))
                .foregroundStyle(color)
                .frame(width: 18, alignment: .center)
                .padding(.top, 1)

            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(.callout.weight(.semibold))
                    .foregroundStyle(color)
                Text(detail)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(11)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 9, style: .continuous)
                .fill(color.opacity(0.09))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 9, style: .continuous)
                .strokeBorder(color.opacity(0.28), lineWidth: 1)
        )
    }
}

// MARK: - Body Setup Profile

public struct BodySetupProfile {
    public let bodyId: String
    public let shortModelName: String
    public let displayName: String
    public let requiredFirmware: String
    public let firmwareBadge: String
    public let firmwareCaution: String?
    public let bodySpecificMovieSetting: String?
    public let stillsModeTitle: String
    public let stillsShortHint: String
    public let stillsModeInstruction: String
    public let isFX3: Bool
    public let isPowerSwitchResetBody: Bool

    public static func forBody(id: String, bodyInfo: BodyInfo?) -> BodySetupProfile {
        switch id {
        case "a7s3_501":
            let fw = bodyInfo?.firmware ?? "5.01"
            return BodySetupProfile(
                bodyId: id,
                shortModelName: "Sony a7S III",
                displayName: bodyInfo?.displayName ?? "a7S III 5.01",
                requiredFirmware: fw,
                firmwareBadge: "a7S III -> Ver. \(fw)",
                firmwareCaution: nil,
                bodySpecificMovieSetting: nil,
                stillsModeTitle: "Mode Dial -> Stills",
                stillsShortHint: "top dial on M / S / A / P",
                stillsModeInstruction: "Turn the top mode dial to a Stills position (M / S / A / P) before booting.",
                isFX3: false,
                isPowerSwitchResetBody: true
            )
        case "fx3_702":
            let fw = bodyInfo?.firmware ?? "7.02"
            return BodySetupProfile(
                bodyId: id,
                shortModelName: "Sony FX3",
                displayName: bodyInfo?.displayName ?? "FX3 7.02",
                requiredFirmware: fw,
                firmwareBadge: "FX3 -> Ver. \(fw) (ILME-FX3 only)",
                firmwareCaution: "Verify Model Name is ILME-FX3 (NOT ILME-FX3A) in MENU > Setup > Setup Option > Version.",
                bodySpecificMovieSetting: "De-Squeeze Display = Off",
                stillsModeTitle: "MODE Button -> Stills",
                stillsShortHint: "MODE button set to Stills",
                stillsModeInstruction: "Press the MODE button and select Stills before connecting USB.",
                isFX3: true,
                isPowerSwitchResetBody: false
            )
        default:
            let fw = bodyInfo?.firmware ?? "2.02"
            return BodySetupProfile(
                bodyId: id,
                shortModelName: "Sony ZV-E1",
                displayName: bodyInfo?.displayName ?? "ZV-E1 2.02",
                requiredFirmware: fw,
                firmwareBadge: "ZV-E1 -> Ver. \(fw)",
                firmwareCaution: nil,
                bodySpecificMovieSetting: "Auto Framing = Off",
                stillsModeTitle: "Still/Movie/S&Q Button -> Still",
                stillsShortHint: "Still/Movie/S&Q set to Still",
                stillsModeInstruction: "Press the top Still/Movie/S&Q button until the camera is in Stills mode.",
                isFX3: false,
                isPowerSwitchResetBody: true
            )
        }
    }
}

// MARK: - Modular Feature Pack Metadata

public enum PackStabilityTier {
    case recommended
    case experimental
    case untestedHardware

    public var badgeText: String {
        switch self {
        case .recommended: return "Recommended"
        case .experimental: return "Experimental"
        case .untestedHardware: return "Untested"
        }
    }

    public var color: Color {
        switch self {
        case .recommended: return .green
        case .experimental: return .orange
        case .untestedHardware: return .orange
        }
    }
}

public struct ModularPackDescriptor: Identifiable {
    public let id: String
    public let title: String
    public let subtitle: String
    public let icon: String
    public let tier: PackStabilityTier

    public static func descriptor(for packId: String, bodyId: String) -> ModularPackDescriptor {
        switch packId {
        case "core_open_gate":
            return ModularPackDescriptor(
                id: packId,
                title: "Open-Gate 3:2 Core",
                subtitle: "Enables 3840x2560 full-sensor 3:2 readout in volatile RAM.",
                icon: "camera.aperture",
                tier: .recommended
            )
        case "mp4_3x2":
            return ModularPackDescriptor(
                id: packId,
                title: "Native 3:2 MP4 & Gyro",
                subtitle: "Writes native 3840x2560 MP4 dimensions and preserves Sony rtmd gyro metadata.",
                icon: "film.stack",
                tier: .recommended
            )
        case "screen_3x2":
            let screenTitle: String
            switch bodyId {
            case "fx3_702":
                screenTitle = "3:2 Rear LCD & Native De-Squeeze"
            case "a7s3_501":
                screenTitle = "3:2 LCD / EVF & C3 Aspect Cycle"
            default:
                screenTitle = "3:2 LCD Framing & C2 Cycle"
            }
            return ModularPackDescriptor(
                id: packId,
                title: screenTitle,
                subtitle: "Uncropped 3:2 viewfinder framing with live aspect cycle or native de-squeeze.",
                icon: "rectangle.aspectratio",
                tier: .recommended
            )
        case "hdmi32":
            return ModularPackDescriptor(
                id: packId,
                title: "HDMI 3:2 Output",
                subtitle: "Outputs a clean 3:2 open-gate feed over HDMI for external monitors and recorders.",
                icon: "display",
                tier: .experimental
            )
        case "high_bitrate":
            return ModularPackDescriptor(
                id: packId,
                title: "High-Bitrate Long-GOP (200M / 300M)",
                subtitle: "Unlocks 200 Mbps and 300 Mbps Long-GOP options in XAVC HS and XAVC S.",
                icon: "speedometer",
                tier: .experimental
            )
        case "xavc_si":
            return ModularPackDescriptor(
                id: packId,
                title: "XAVC S-I All-Intra 3:2",
                subtitle: "Enables 3:2 open-gate recording in XAVC S-I intra-frame mode (24p / 25p / 30p).",
                icon: "waveform.path.ecg.rectangle",
                tier: .experimental
            )
        case "fx3_playback":
            return ModularPackDescriptor(
                id: packId,
                title: "FX3 Open-Gate Playback Fix",
                subtitle: "Experimental FX3 playback path patch for 3:2 open-gate clips (untested on hardware).",
                icon: "play.rectangle.on.rectangle",
                tier: .untestedHardware
            )
        default:
            return ModularPackDescriptor(
                id: packId,
                title: packId,
                subtitle: "",
                icon: "puzzlepiece",
                tier: .experimental
            )
        }
    }
}

// MARK: - Mock Camera State Friendly Labels

extension MockCameraState {
    public var friendlyName: String {
        switch self {
        case .stock:
            return "Clean Stock"
        case .mixedPowerswitch:
            return "Warm Power-Switch (Blocked)"
        case .applied:
            return "Open-Gate Active"
        }
    }
}

// MARK: - 3:2 Cinema Framing Preview Canvas

public struct DeliveryFramingCanvas: View {
    public let sourceWidth: Int
    public let sourceHeight: Int
    public let spec: DeliveryCropSpec?
    public let showActionSafe: Bool
    public let showTitleSafe: Bool

    public init(
        sourceWidth: Int,
        sourceHeight: Int,
        spec: DeliveryCropSpec?,
        showActionSafe: Bool,
        showTitleSafe: Bool
    ) {
        self.sourceWidth = sourceWidth
        self.sourceHeight = sourceHeight
        self.spec = spec
        self.showActionSafe = showActionSafe
        self.showTitleSafe = showTitleSafe
    }

    public var body: some View {
        GeometryReader { geo in
            let safeW = max(Double(sourceWidth), 1)
            let safeH = max(Double(sourceHeight), 1)
            let candidateH = geo.size.width * (safeH / safeW)
            let displayH = min(candidateH, geo.size.height)
            let displayW = displayH * (safeW / safeH)

            ZStack(alignment: .topLeading) {
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .fill(Color(white: 0.08))
                    .frame(width: displayW, height: displayH)

                if let spec {
                    let cropW = displayW * spec.normRect.width
                    let cropH = displayH * spec.normRect.height
                    let cropX = displayW * spec.normRect.x
                    let cropY = displayH * spec.normRect.y

                    // Dimmed matte outside active delivery crop
                    Path { path in
                        path.addRect(CGRect(x: 0, y: 0, width: displayW, height: displayH))
                        path.addRect(CGRect(x: cropX, y: cropY, width: cropW, height: cropH))
                    }
                    .fill(Color.black.opacity(0.45), style: FillStyle(eoFill: true))
                    .frame(width: displayW, height: displayH)
                    .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))

                    Rectangle()
                        .fill(Color.accentColor.opacity(0.10))
                        .overlay(
                            Rectangle()
                                .stroke(Color.white.opacity(0.92), lineWidth: 1.75)
                        )
                        .frame(width: cropW, height: cropH)
                        .offset(x: cropX, y: cropY)

                    if showActionSafe, let action = spec.actionSafe {
                        Rectangle()
                            .stroke(Color.yellow.opacity(0.80), style: StrokeStyle(lineWidth: 1, dash: [5, 4]))
                            .frame(
                                width: displayW * action.normRect.width,
                                height: displayH * action.normRect.height
                            )
                            .offset(
                                x: displayW * action.normRect.x,
                                y: displayH * action.normRect.y
                            )
                    }

                    if showTitleSafe, let title = spec.titleSafe {
                        Rectangle()
                            .stroke(Color.green.opacity(0.80), style: StrokeStyle(lineWidth: 1, dash: [3, 3]))
                            .frame(
                                width: displayW * title.normRect.width,
                                height: displayH * title.normRect.height
                            )
                            .offset(
                                x: displayW * title.normRect.x,
                                y: displayH * title.normRect.y
                            )
                    }

                    Text("\(spec.aspect)  ·  \(spec.width)×\(spec.height)")
                        .font(.caption2.weight(.semibold).monospacedDigit())
                        .foregroundStyle(.white)
                        .padding(.horizontal, 8)
                        .padding(.vertical, 3)
                        .background(Color.black.opacity(0.68))
                        .clipShape(Capsule())
                        .offset(x: cropX + 8, y: cropY + 8)
                }
            }
            .overlay(
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .strokeBorder(Color.white.opacity(0.12), lineWidth: 1)
                    .frame(width: displayW, height: displayH)
            )
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)
        }
    }
}
