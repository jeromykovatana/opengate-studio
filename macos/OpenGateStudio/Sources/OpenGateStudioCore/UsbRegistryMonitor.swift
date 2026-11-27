import Foundation
import IOKit

public enum UsbRegistryMonitor {
    private struct SonyUsbCandidate {
        let bodyId: String?
        let usbProductName: String?
        let usbMode: String
        let isFx3aBlocked: Bool
        let warning: String?
    }

    /// Reads the IOKit USB registry passively (zero USB packets sent) for a connected Sony camera.
    /// Returns `nil` when `OPENGATE_MOCK_IOREG_FILE` is configured so callers fall back to `StudioBridge.detectUsbCamera()`.
    public static func detectConnectedSonyCamera() -> DetectedUsbCameraResult? {
        if let mockPath = ProcessInfo.processInfo.environment["OPENGATE_MOCK_IOREG_FILE"]?
            .trimmingCharacters(in: .whitespacesAndNewlines),
           !mockPath.isEmpty {
            return nil
        }

        guard let matching = IOServiceMatching("IOUSBHostDevice") else {
            return nil
        }

        var iterator: io_iterator_t = 0
        let kr = IOServiceGetMatchingServices(kIOMainPortDefault, matching, &iterator)
        guard kr == KERN_SUCCESS else {
            return nil
        }
        defer { IOObjectRelease(iterator) }

        var candidates: [SonyUsbCandidate] = []

        while true {
            let service = IOIteratorNext(iterator)
            guard service != 0 else { break }
            defer { IOObjectRelease(service) }

            let props = readProperties(of: service)
            guard intValue(props["idVendor"]) == 0x054C else {
                continue
            }

            let idProduct = intValue(props["idProduct"])
            let productName = readProductName(entry: service, props: props)
            let (ifaceClasses, hasMscDriver) = collectInterfaceAndDriverInfo(for: service, rootProps: props)

            let usbMode: String
            if idProduct == 0x0336 || idProduct == 0x02A9 || ifaceClasses.contains(255) {
                usbMode = "service"
            } else if ifaceClasses.contains(8) || hasMscDriver {
                usbMode = "msc"
            } else {
                usbMode = "other"
            }

            let mapped = mapSonyUsbProduct(productName)
            candidates.append(
                SonyUsbCandidate(
                    bodyId: mapped.bodyId,
                    usbProductName: productName,
                    usbMode: usbMode,
                    isFx3aBlocked: mapped.isFx3aBlocked,
                    warning: mapped.warning
                )
            )
        }

        guard !candidates.isEmpty else {
            return DetectedUsbCameraResult(
                ok: true,
                detected: false,
                bodyId: nil,
                usbProductName: nil,
                usbMode: nil,
                isFx3aBlocked: false,
                warning: nil
            )
        }

        let chosen = candidates.first(where: { $0.bodyId != nil || $0.isFx3aBlocked }) ?? candidates[0]
        return DetectedUsbCameraResult(
            ok: true,
            detected: true,
            bodyId: chosen.bodyId,
            usbProductName: chosen.usbProductName,
            usbMode: chosen.usbMode,
            isFx3aBlocked: chosen.isFx3aBlocked,
            warning: chosen.warning
        )
    }

    /// Maps a Sony USB product string to an OpenGate Studio body ID or FX3A block status.
    public static func mapSonyUsbProduct(
        _ rawName: String?
    ) -> (bodyId: String?, isFx3aBlocked: Bool, warning: String?) {
        guard let rawName else {
            return (nil, false, nil)
        }
        let upper = rawName.trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
        guard !upper.isEmpty else {
            return (nil, false, nil)
        }

        if upper.contains("ILME-FX3A") || containsToken(upper, "FX3A") {
            return (nil, true, "ILME-FX3A is not supported by FX3 7.02 kits")
        }

        // Check ZV-E10 before ZV-E1 because "ZV-E10" begins with "ZV-E1".
        if upper.contains("ZV-E10") || upper.contains("ZVE10") {
            return ("zve10_203", false, nil)
        }

        if containsToken(upper, "ZV-E1") || containsToken(upper, "ZVE1") {
            return ("zve1_202", false, nil)
        }

        if upper.contains("ILCE-7SM3")
            || containsToken(upper, "7SM3")
            || upper.contains("A7S III")
            || upper.contains("A7SIII") {
            return ("a7s3_501", false, nil)
        }

        if !upper.contains("FX30")
            && !upper.contains("FX3A")
            && (upper.contains("ILME-FX3") || containsToken(upper, "FX3")) {
            return ("fx3_702", false, nil)
        }

        let isExcluded7C = upper.contains("7CM2")
            || upper.contains("7CR")
            || upper.contains("A7C II")
            || upper.contains("A7CII")
            || upper.contains("A7C R")
            || upper.contains("A7CR")
        if !isExcluded7C && (containsToken(upper, "ILCE-7C") || containsToken(upper, "A7C")) {
            return ("a7c_203", false, nil)
        }

        return (nil, false, nil)
    }

    private static func readProperties(of entry: io_registry_entry_t) -> [String: Any] {
        var propsRef: Unmanaged<CFMutableDictionary>?
        let kr = IORegistryEntryCreateCFProperties(entry, &propsRef, kCFAllocatorDefault, 0)
        guard kr == KERN_SUCCESS, let dict = propsRef?.takeRetainedValue() as? [String: Any] else {
            return [:]
        }
        return dict
    }

    private static func intValue(_ value: Any?) -> Int? {
        if let num = value as? NSNumber {
            return num.intValue
        }
        if let intVal = value as? Int {
            return intVal
        }
        return nil
    }

    private static func entryName(_ entry: io_registry_entry_t) -> String? {
        var buffer = [CChar](repeating: 0, count: MemoryLayout<io_name_t>.size)
        let kr = buffer.withUnsafeMutableBufferPointer { ptr -> kern_return_t in
            guard let base = ptr.baseAddress else { return KERN_FAILURE }
            return IORegistryEntryGetName(entry, base)
        }
        guard kr == KERN_SUCCESS else {
            return nil
        }
        let name = buffer.withUnsafeBufferPointer { ptr -> String in
            guard let base = ptr.baseAddress else { return "" }
            return String(cString: base)
        }.trimmingCharacters(in: .whitespacesAndNewlines)
        return name.isEmpty ? nil : name
    }

    private static func readProductName(entry: io_registry_entry_t, props: [String: Any]) -> String? {
        for key in ["USB Product Name", "Product Name", "kUSBProductString"] {
            if let str = props[key] as? String {
                let trimmed = str.trimmingCharacters(in: .whitespacesAndNewlines)
                if !trimmed.isEmpty {
                    return trimmed
                }
            }
        }
        return entryName(entry)
    }

    private static func collectInterfaceAndDriverInfo(
        for service: io_registry_entry_t,
        rootProps: [String: Any]
    ) -> (ifaceClasses: [Int], hasMscDriver: Bool) {
        var ifaceClasses: [Int] = []
        var hasMscDriver = false

        if let cls = intValue(rootProps["bInterfaceClass"]) {
            ifaceClasses.append(cls)
        }
        if entryMatchesMassStorage(entry: service, props: rootProps) {
            hasMscDriver = true
        }

        var descIter: io_iterator_t = 0
        let kr = IORegistryEntryCreateIterator(
            service,
            kIOServicePlane,
            IOOptionBits(kIORegistryIterateRecursively),
            &descIter
        )
        guard kr == KERN_SUCCESS else {
            return (ifaceClasses, hasMscDriver)
        }
        defer { IOObjectRelease(descIter) }

        while true {
            let desc = IOIteratorNext(descIter)
            guard desc != 0 else { break }
            defer { IOObjectRelease(desc) }

            let descProps = readProperties(of: desc)
            if let cls = intValue(descProps["bInterfaceClass"]) {
                ifaceClasses.append(cls)
            }
            if !hasMscDriver && entryMatchesMassStorage(entry: desc, props: descProps) {
                hasMscDriver = true
            }
        }

        return (ifaceClasses, hasMscDriver)
    }

    private static func entryMatchesMassStorage(entry: io_registry_entry_t, props: [String: Any]) -> Bool {
        if let className = IOObjectCopyClass(entry)?.takeRetainedValue() as String?,
           className.contains("IOUSBMassStorage") {
            return true
        }
        if let ioClass = props["IOClass"] as? String, ioClass.contains("IOUSBMassStorage") {
            return true
        }
        if let name = entryName(entry), name.contains("IOUSBMassStorage") {
            return true
        }
        return false
    }

    private static func containsToken(_ uppercasedText: String, _ uppercasedToken: String) -> Bool {
        var searchStart = uppercasedText.startIndex
        while searchStart < uppercasedText.endIndex,
              let range = uppercasedText.range(of: uppercasedToken, range: searchStart..<uppercasedText.endIndex) {
            let leftOk: Bool
            if range.lowerBound == uppercasedText.startIndex {
                leftOk = true
            } else {
                let prev = uppercasedText[uppercasedText.index(before: range.lowerBound)]
                leftOk = !isAsciiAlnum(prev)
            }

            let rightOk: Bool
            if range.upperBound == uppercasedText.endIndex {
                rightOk = true
            } else {
                let next = uppercasedText[range.upperBound]
                rightOk = !isAsciiAlnum(next)
            }

            if leftOk && rightOk {
                return true
            }
            searchStart = range.upperBound
        }
        return false
    }

    private static func isAsciiAlnum(_ ch: Character) -> Bool {
        guard let scalar = ch.unicodeScalars.first, ch.unicodeScalars.count == 1 else {
            return false
        }
        return (scalar.value >= 0x30 && scalar.value <= 0x39)
            || (scalar.value >= 0x41 && scalar.value <= 0x5A)
            || (scalar.value >= 0x61 && scalar.value <= 0x7A)
    }
}
