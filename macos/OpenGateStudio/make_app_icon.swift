import AppKit
import CoreGraphics
import Foundation

struct IconSpec {
    let filename: String
    let pixels: Int
}

let specs: [IconSpec] = [
    IconSpec(filename: "icon_16x16.png", pixels: 16),
    IconSpec(filename: "icon_16x16@2x.png", pixels: 32),
    IconSpec(filename: "icon_32x32.png", pixels: 32),
    IconSpec(filename: "icon_32x32@2x.png", pixels: 64),
    IconSpec(filename: "icon_128x128.png", pixels: 128),
    IconSpec(filename: "icon_128x128@2x.png", pixels: 256),
    IconSpec(filename: "icon_256x256.png", pixels: 256),
    IconSpec(filename: "icon_256x256@2x.png", pixels: 512),
    IconSpec(filename: "icon_512x512.png", pixels: 512),
    IconSpec(filename: "icon_512x512@2x.png", pixels: 1024),
]

func squirclePath(in rect: CGRect, cornerRadius: CGFloat) -> CGPath {
    NSBezierPath(roundedRect: rect, xRadius: cornerRadius, yRadius: cornerRadius).cgPathCompat
}

extension NSBezierPath {
    var cgPathCompat: CGPath {
        let path = CGMutablePath()
        var points = [CGPoint](repeating: .zero, count: 3)
        for i in 0..<elementCount {
            let type = element(at: i, associatedPoints: &points)
            switch type {
            case .moveTo:
                path.move(to: points[0])
            case .lineTo:
                path.addLine(to: points[0])
            case .curveTo:
                path.addCurve(to: points[2], control1: points[0], control2: points[1])
            case .closePath:
                path.closeSubpath()
            case .cubicCurveTo:
                path.addCurve(to: points[2], control1: points[0], control2: points[1])
            case .quadraticCurveTo:
                path.addQuadCurve(to: points[1], control: points[0])
            @unknown default:
                break
            }
        }
        return path
    }
}

func renderIcon(pixels: Int) -> Data? {
    let s = CGFloat(pixels)
    guard let rep = NSBitmapImageRep(
        bitmapDataPlanes: nil,
        pixelsWide: pixels,
        pixelsHigh: pixels,
        bitsPerSample: 8,
        samplesPerPixel: 4,
        hasAlpha: true,
        isPlanar: false,
        colorSpaceName: .deviceRGB,
        bytesPerRow: 0,
        bitsPerPixel: 0
    ) else {
        return nil
    }
    rep.size = NSSize(width: s, height: s)

    guard let ctx = NSGraphicsContext(bitmapImageRep: rep)?.cgContext else {
        return nil
    }

    ctx.setShouldAntialias(true)
    ctx.setAllowsAntialiasing(true)
    ctx.interpolationQuality = .high

    let colorSpace = CGColorSpaceCreateDeviceRGB()

    // macOS icon squircle canvas (~10% outer margin on 1024x1024 grid)
    let margin = s * 0.095
    let squircleRect = CGRect(x: margin, y: margin, width: s - 2 * margin, height: s - 2 * margin)
    let cornerRadius = squircleRect.width * 0.225
    let bodyPath = CGPath(roundedRect: squircleRect, cornerWidth: cornerRadius, cornerHeight: cornerRadius, transform: nil)

    // Subtle drop shadow for icon body
    ctx.saveGState()
    ctx.setShadow(offset: CGSize(width: 0, height: -s * 0.018), blur: s * 0.045, color: CGColor(red: 0, green: 0, blue: 0, alpha: 0.45))
    ctx.addPath(bodyPath)
    ctx.setFillColor(CGColor(red: 0.06, green: 0.09, blue: 0.14, alpha: 1.0))
    ctx.fillPath()
    ctx.restoreGState()

    // Dark-slate background gradient clipped to squircle
    ctx.saveGState()
    ctx.addPath(bodyPath)
    ctx.clip()

    let bgColors = [
        CGColor(red: 0.055, green: 0.082, blue: 0.125, alpha: 1.0),
        CGColor(red: 0.095, green: 0.135, blue: 0.195, alpha: 1.0),
        CGColor(red: 0.125, green: 0.175, blue: 0.245, alpha: 1.0),
    ] as CFArray
    if let bgGrad = CGGradient(colorsSpace: colorSpace, colors: bgColors, locations: [0.0, 0.55, 1.0]) {
        ctx.drawLinearGradient(
            bgGrad,
            start: CGPoint(x: squircleRect.minX, y: squircleRect.minY),
            end: CGPoint(x: squircleRect.maxX, y: squircleRect.maxY),
            options: []
        )
    }

    // Subtle radial emerald/cyan glow behind the 3:2 sensor frame
    let center = CGPoint(x: s * 0.5, y: s * 0.5)
    let glowColors = [
        CGColor(red: 0.06, green: 0.80, blue: 0.62, alpha: 0.24),
        CGColor(red: 0.02, green: 0.65, blue: 0.85, alpha: 0.10),
        CGColor(red: 0.0, green: 0.0, blue: 0.0, alpha: 0.0),
    ] as CFArray
    if let glowGrad = CGGradient(colorsSpace: colorSpace, colors: glowColors, locations: [0.0, 0.45, 1.0]) {
        ctx.drawRadialGradient(
            glowGrad,
            startCenter: center,
            startRadius: 0,
            endCenter: center,
            endRadius: squircleRect.width * 0.56,
            options: []
        )
    }
    ctx.restoreGState()

    // Crisp dark-slate rim highlight
    ctx.saveGState()
    ctx.addPath(bodyPath)
    ctx.setStrokeColor(CGColor(red: 0.65, green: 0.85, blue: 0.95, alpha: 0.18))
    ctx.setLineWidth(max(1.0, s * 0.008))
    ctx.strokePath()
    ctx.restoreGState()

    // 3:2 Open-Gate Sensor Frame
    let frameWidth = squircleRect.width * 0.66
    let frameHeight = frameWidth * (2.0 / 3.0)
    let sensorRect = CGRect(
        x: (s - frameWidth) * 0.5,
        y: (s - frameHeight) * 0.5,
        width: frameWidth,
        height: frameHeight
    )
    let sensorCorner = max(1.5, s * 0.022)
    let sensorPath = CGPath(roundedRect: sensorRect, cornerWidth: sensorCorner, cornerHeight: sensorCorner, transform: nil)

    // Subtle translucent fill inside 3:2 sensor
    ctx.saveGState()
    ctx.addPath(sensorPath)
    ctx.setFillColor(CGColor(red: 0.06, green: 0.72, blue: 0.60, alpha: 0.11))
    ctx.fillPath()
    ctx.restoreGState()

    // Glowing emerald -> cyan 3:2 frame stroke
    let sensorStrokeWidth = max(1.4, s * 0.026)
    ctx.saveGState()
    ctx.setShadow(
        offset: .zero,
        blur: max(1.5, s * 0.045),
        color: CGColor(red: 0.08, green: 0.90, blue: 0.68, alpha: 0.78)
    )
    ctx.addPath(sensorPath)
    ctx.setLineWidth(sensorStrokeWidth)
    ctx.replacePathWithStrokedPath()
    ctx.clip()

    let gradRect = sensorRect.insetBy(dx: -sensorStrokeWidth, dy: -sensorStrokeWidth)
    let strokeColors = [
        CGColor(red: 0.10, green: 0.88, blue: 0.55, alpha: 1.0), // Emerald
        CGColor(red: 0.05, green: 0.82, blue: 0.88, alpha: 1.0), // Cyan
    ] as CFArray
    if let strokeGrad = CGGradient(colorsSpace: colorSpace, colors: strokeColors, locations: [0.0, 1.0]) {
        ctx.drawLinearGradient(
            strokeGrad,
            start: CGPoint(x: gradRect.minX, y: gradRect.maxY),
            end: CGPoint(x: gradRect.maxX, y: gradRect.minY),
            options: [.drawsBeforeStartLocation, .drawsAfterEndLocation]
        )
    }
    ctx.restoreGState()

    // Inner dashed 16:9 crop frame (showing extra 3:2 headroom/footroom)
    let cropWidth = sensorRect.width * 0.86
    let cropHeight = cropWidth * (9.0 / 16.0)
    let cropRect = CGRect(
        x: (s - cropWidth) * 0.5,
        y: (s - cropHeight) * 0.5,
        width: cropWidth,
        height: cropHeight
    )
    let cropCorner = max(1.0, s * 0.012)
    let cropPath = CGPath(roundedRect: cropRect, cornerWidth: cropCorner, cornerHeight: cropCorner, transform: nil)

    ctx.saveGState()
    ctx.addPath(cropPath)
    let dashLen = max(2.0, s * 0.036)
    let gapLen = max(1.5, s * 0.024)
    ctx.setLineDash(phase: 0, lengths: [dashLen, gapLen])
    ctx.setLineCap(.round)
    ctx.setLineWidth(max(1.0, s * 0.014))
    ctx.setStrokeColor(CGColor(red: 0.82, green: 0.96, blue: 1.0, alpha: 0.72))
    ctx.strokePath()
    ctx.restoreGState()

    // Subtle corner viewfinder brackets outside the 3:2 frame
    let pad = s * 0.042
    let bracketLen = s * 0.075
    let outerRect = sensorRect.insetBy(dx: -pad, dy: -pad)

    ctx.saveGState()
    ctx.setStrokeColor(CGColor(red: 0.45, green: 0.95, blue: 0.86, alpha: 0.88))
    ctx.setLineWidth(max(1.0, s * 0.015))
    ctx.setLineCap(.round)
    ctx.setLineJoin(.round)

    // Bottom-left
    ctx.move(to: CGPoint(x: outerRect.minX, y: outerRect.minY + bracketLen))
    ctx.addLine(to: CGPoint(x: outerRect.minX, y: outerRect.minY))
    ctx.addLine(to: CGPoint(x: outerRect.minX + bracketLen, y: outerRect.minY))

    // Bottom-right
    ctx.move(to: CGPoint(x: outerRect.maxX - bracketLen, y: outerRect.minY))
    ctx.addLine(to: CGPoint(x: outerRect.maxX, y: outerRect.minY))
    ctx.addLine(to: CGPoint(x: outerRect.maxX, y: outerRect.minY + bracketLen))

    // Top-left
    ctx.move(to: CGPoint(x: outerRect.minX, y: outerRect.maxY - bracketLen))
    ctx.addLine(to: CGPoint(x: outerRect.minX, y: outerRect.maxY))
    ctx.addLine(to: CGPoint(x: outerRect.minX + bracketLen, y: outerRect.maxY))

    // Top-right
    ctx.move(to: CGPoint(x: outerRect.maxX - bracketLen, y: outerRect.maxY))
    ctx.addLine(to: CGPoint(x: outerRect.maxX, y: outerRect.maxY))
    ctx.addLine(to: CGPoint(x: outerRect.maxX, y: outerRect.maxY - bracketLen))

    ctx.strokePath()
    ctx.restoreGState()

    // Center focus crosshair dot (subtle, scales cleanly)
    if pixels >= 32 {
        let dotR = max(1.0, s * 0.012)
        let dotRect = CGRect(x: center.x - dotR, y: center.y - dotR, width: dotR * 2, height: dotR * 2)
        ctx.saveGState()
        ctx.setFillColor(CGColor(red: 0.45, green: 0.96, blue: 0.85, alpha: 0.85))
        ctx.fillEllipse(in: dotRect)
        ctx.restoreGState()
    }

    return rep.representation(using: .png, properties: [:])
}

let scriptDir = URL(fileURLWithPath: CommandLine.arguments[0]).deletingLastPathComponent()
let resourcesDir = scriptDir.appendingPathComponent("Resources", isDirectory: true)
let iconsetDir = FileManager.default.temporaryDirectory.appendingPathComponent("OpenGateAppIcon_\(ProcessInfo.processInfo.processIdentifier).iconset", isDirectory: true)
let outputIcns = resourcesDir.appendingPathComponent("AppIcon.icns")

try FileManager.default.createDirectory(at: resourcesDir, withIntermediateDirectories: true)
try FileManager.default.createDirectory(at: iconsetDir, withIntermediateDirectories: true)
defer {
    try? FileManager.default.removeItem(at: iconsetDir)
}

for spec in specs {
    guard let pngData = renderIcon(pixels: spec.pixels) else {
        fputs("ERROR: failed to render \(spec.filename)\n", stderr)
        exit(1)
    }
    let dest = iconsetDir.appendingPathComponent(spec.filename)
    try pngData.write(to: dest)
}

let proc = Process()
proc.executableURL = URL(fileURLWithPath: "/usr/bin/iconutil")
proc.arguments = ["-c", "icns", iconsetDir.path, "-o", outputIcns.path]
try proc.run()
proc.waitUntilExit()

if proc.terminationStatus != 0 {
    fputs("ERROR: iconutil exited with status \(proc.terminationStatus)\n", stderr)
    exit(proc.terminationStatus)
}

print("Generated \(outputIcns.path)")
