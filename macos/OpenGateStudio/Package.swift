// swift-tools-version: 5.10
import Foundation
import PackageDescription

let cltFrameworksPath = "/Library/Developer/CommandLineTools/Library/Developer/Frameworks"
let cltUsrLibPath = "/Library/Developer/CommandLineTools/Library/Developer/usr/lib"
let useCLTTestingPaths = FileManager.default.fileExists(atPath: "\(cltFrameworksPath)/Testing.framework")

let testSwiftSettings: [SwiftSetting] = useCLTTestingPaths
    ? [.unsafeFlags(["-F", cltFrameworksPath])]
    : []

let testLinkerSettings: [LinkerSetting] = useCLTTestingPaths
    ? [.unsafeFlags([
        "-F", cltFrameworksPath,
        "-Xlinker", "-rpath", "-Xlinker", cltFrameworksPath,
        "-Xlinker", "-rpath", "-Xlinker", cltUsrLibPath
    ])]
    : []

let package = Package(
    name: "OpenGateStudio",
    platforms: [
        .macOS(.v14)
    ],
    products: [
        .library(
            name: "OpenGateStudioCore",
            targets: ["OpenGateStudioCore"]
        ),
        .executable(
            name: "OpenGateStudio",
            targets: ["OpenGateStudio"]
        )
    ],
    targets: [
        .target(
            name: "OpenGateStudioCore",
            path: "Sources/OpenGateStudioCore"
        ),
        .executableTarget(
            name: "OpenGateStudio",
            dependencies: ["OpenGateStudioCore"],
            path: "Sources/OpenGateStudio"
        ),
        .testTarget(
            name: "OpenGateStudioTests",
            dependencies: ["OpenGateStudioCore"],
            path: "Tests/OpenGateStudioTests",
            swiftSettings: testSwiftSettings,
            linkerSettings: testLinkerSettings
        )
    ]
)
