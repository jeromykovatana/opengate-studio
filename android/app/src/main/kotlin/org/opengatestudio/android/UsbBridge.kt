package org.opengatestudio.android

import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbDeviceConnection
import android.hardware.usb.UsbEndpoint
import android.hardware.usb.UsbInterface
import android.hardware.usb.UsbManager
import android.os.Build
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Clean-room Android USB Host bridge backing `opengate_android.usb_bridge_shim`.
 *
 * Handles Sony VID 0x054C enumeration, forceful kernel MSC driver detachment via
 * `claimInterface(iface, true)`, 30s service-mode permission waiting across USB replugs,
 * and cooperative cancellation between steps.
 */
class UsbBridge(private val context: Context) {
    companion object {
        const val SONY_VID: Int = 0x054C
        const val DEFAULT_PERMISSION_TIMEOUT_MS: Long = 30_000L
        private const val ACTION_USB_PERMISSION = "org.opengatestudio.android.USB_PERMISSION"
    }

    data class OpenHandle(
        val device: UsbDevice,
        val connection: UsbDeviceConnection,
        val claimedInterfaces: List<UsbInterface>,
        val endpointsByAddress: Map<Int, UsbEndpoint>
    )

    private val usbManager: UsbManager =
        context.getSystemService(Context.USB_SERVICE) as UsbManager
    private val openHandles = ConcurrentHashMap<Int, OpenHandle>()

    fun findDevices(vendorId: Int?): List<Map<String, Any>> {
        val targetVid = vendorId ?: SONY_VID
        return usbManager.deviceList.values
            .filter { it.vendorId == targetVid }
            .sortedBy { it.deviceId }
            .map { dev ->
                val ifaces = (0 until dev.interfaceCount).map { idx ->
                    val iface = dev.getInterface(idx)
                    val eps = (0 until iface.endpointCount).map { eIdx ->
                        val ep = iface.getEndpoint(eIdx)
                        mapOf(
                            "address" to ep.address,
                            "attributes" to ep.attributes,
                            "maxPacketSize" to ep.maxPacketSize
                        )
                    }
                    mapOf(
                        "number" to iface.id,
                        "interfaceClass" to iface.interfaceClass,
                        "interfaceProtocol" to iface.interfaceProtocol,
                        "endpoints" to eps
                    )
                }
                val serial = runCatching {
                    if (usbManager.hasPermission(dev)) dev.serialNumber ?: "" else ""
                }.getOrDefault("")
                val productName = runCatching { dev.productName ?: "" }.getOrDefault("")
                mapOf(
                    "deviceId" to dev.deviceId,
                    "idVendor" to dev.vendorId,
                    "idProduct" to dev.productId,
                    "productName" to productName,
                    "serialNumber" to serial,
                    "interfaces" to ifaces
                )
            }
    }

    fun openAndClaim(deviceId: Int, timeoutMs: Int): Int? {
        val device = usbManager.deviceList.values.firstOrNull { it.deviceId == deviceId }
            ?: return null

        if (!usbManager.hasPermission(device)) {
            val granted = requestPermissionBlocking(device, timeoutMs.toLong())
            if (!granted) return null
        }

        val connection = usbManager.openDevice(device) ?: return null
        val claimed = mutableListOf<UsbInterface>()
        val endpoints = mutableMapOf<Int, UsbEndpoint>()

        for (i in 0 until device.interfaceCount) {
            val iface = device.getInterface(i)
            // Force-claim detaches Android's built-in USB Mass Storage driver.
            if (connection.claimInterface(iface, true)) {
                claimed.add(iface)
                for (e in 0 until iface.endpointCount) {
                    val ep = iface.getEndpoint(e)
                    endpoints[ep.address] = ep
                }
            }
        }

        if (claimed.isEmpty()) {
            connection.close()
            return null
        }

        openHandles[deviceId] = OpenHandle(device, connection, claimed, endpoints)
        return deviceId
    }

    fun bulkRead(handleId: Int, epAddress: Int, length: Int, timeoutMs: Int): ByteArray {
        val handle = openHandles[handleId] ?: error("Unknown USB handle $handleId")
        val endpoint = handle.endpointsByAddress[epAddress]
            ?: error("Unknown IN endpoint 0x${epAddress.toString(16)}")
        val buf = ByteArray(length)
        val n = handle.connection.bulkTransfer(endpoint, buf, length, timeoutMs)
        if (n < 0) error("bulkTransfer read failed ($n)")
        return buf.copyOf(n)
    }

    fun bulkWrite(handleId: Int, epAddress: Int, data: ByteArray, timeoutMs: Int): Int {
        val handle = openHandles[handleId] ?: error("Unknown USB handle $handleId")
        val endpoint = handle.endpointsByAddress[epAddress]
            ?: error("Unknown OUT endpoint 0x${epAddress.toString(16)}")
        val n = handle.connection.bulkTransfer(endpoint, data, data.size, timeoutMs)
        if (n < 0) error("bulkTransfer write failed ($n)")
        return n
    }

    fun controlTransferIn(
        handleId: Int,
        requestType: Int,
        request: Int,
        value: Int,
        index: Int,
        length: Int,
        timeoutMs: Int
    ): ByteArray {
        val handle = openHandles[handleId] ?: error("Unknown USB handle $handleId")
        val buf = ByteArray(length)
        val n = handle.connection.controlTransfer(
            requestType,
            request,
            value,
            index,
            buf,
            buf.size,
            timeoutMs
        )
        if (n < 0) error("controlTransfer IN failed ($n)")
        return buf.copyOf(n)
    }

    fun controlTransferOut(
        handleId: Int,
        requestType: Int,
        request: Int,
        value: Int,
        index: Int,
        data: ByteArray,
        timeoutMs: Int
    ): Int {
        val handle = openHandles[handleId] ?: error("Unknown USB handle $handleId")
        val n = handle.connection.controlTransfer(
            requestType,
            request,
            value,
            index,
            data,
            data.size,
            timeoutMs
        )
        if (n < 0) error("controlTransfer OUT failed ($n)")
        return n
    }

    fun controlTransfer(
        handleId: Int,
        requestType: Int,
        request: Int,
        value: Int,
        index: Int,
        dataOrLength: Any,
        timeoutMs: Int
    ): Any {
        return when (dataOrLength) {
            is Int -> controlTransferIn(handleId, requestType, request, value, index, dataOrLength, timeoutMs)
            is ByteArray -> controlTransferOut(handleId, requestType, request, value, index, dataOrLength, timeoutMs)
            else -> error("Unsupported controlTransfer payload: $dataOrLength")
        }
    }

    fun close(handleId: Int) {
        val handle = openHandles.remove(handleId) ?: return
        handle.claimedInterfaces.forEach { iface ->
            runCatching { handle.connection.releaseInterface(iface) }
        }
        runCatching { handle.connection.close() }
    }

    private fun requestPermissionBlocking(device: UsbDevice, timeoutMs: Long): Boolean {
        val granted = AtomicBoolean(false)
        val latch = CountDownLatch(1)

        val receiver = object : BroadcastReceiver() {
            override fun onReceive(ctx: Context?, intent: Intent?) {
                if (intent?.action == ACTION_USB_PERMISSION) {
                    val allowed = intent.getBooleanExtra(UsbManager.EXTRA_PERMISSION_GRANTED, false)
                    granted.set(allowed)
                    latch.countDown()
                }
            }
        }

        val flags = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_MUTABLE
        } else {
            PendingIntent.FLAG_UPDATE_CURRENT
        }
        val permIntent = PendingIntent.getBroadcast(context, device.deviceId, Intent(ACTION_USB_PERMISSION), flags)
        val filter = IntentFilter(ACTION_USB_PERMISSION)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            context.registerReceiver(receiver, filter, Context.RECEIVER_NOT_EXPORTED)
        } else {
            @Suppress("DEPRECATION")
            context.registerReceiver(receiver, filter)
        }

        try {
            usbManager.requestPermission(device, permIntent)
            val waitMs = timeoutMs.coerceAtLeast(DEFAULT_PERMISSION_TIMEOUT_MS)
            latch.await(waitMs, TimeUnit.MILLISECONDS)
        } finally {
            runCatching { context.unregisterReceiver(receiver) }
        }
        return granted.get()
    }
}
