package org.opengatestudio.android

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import java.io.File
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Keeps USB-OTG step execution alive across dial switches and cable replugs
 * with a partial WakeLock and between-step `cancel.flag` signaling.
 */
class OpenGateForegroundService : Service() {
    companion object {
        const val CHANNEL_ID = "opengate_usb_session"
        const val NOTIFICATION_ID = 1001
        const val ACTION_START_SESSION = "org.opengatestudio.android.START_SESSION"
        const val ACTION_UPDATE_STATUS = "org.opengatestudio.android.UPDATE_STATUS"
        const val ACTION_STOP_SESSION = "org.opengatestudio.android.STOP_SESSION"
        const val ACTION_CANCEL_SAFELY = "org.opengatestudio.android.CANCEL_SAFELY"
        const val EXTRA_STATUS_TEXT = "status_text"

        fun startSession(context: Context, statusText: String = "Running OpenGate companion step…") {
            val intent = Intent(context, OpenGateForegroundService::class.java).apply {
                action = ACTION_START_SESSION
                putExtra(EXTRA_STATUS_TEXT, statusText)
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(intent)
            } else {
                context.startService(intent)
            }
        }

        fun updateStatus(context: Context, statusText: String) {
            val intent = Intent(context, OpenGateForegroundService::class.java).apply {
                action = ACTION_UPDATE_STATUS
                putExtra(EXTRA_STATUS_TEXT, statusText)
            }
            context.startService(intent)
        }

        fun requestSafeCancel(context: Context) {
            val runDir = File(context.filesDir, "active_run").apply { mkdirs() }
            File(runDir, "cancel.flag").writeText("cancel\n")
            val intent = Intent(context, OpenGateForegroundService::class.java).apply {
                action = ACTION_CANCEL_SAFELY
            }
            context.startService(intent)
        }

        fun stopSession(context: Context) {
            val intent = Intent(context, OpenGateForegroundService::class.java).apply {
                action = ACTION_STOP_SESSION
            }
            context.startService(intent)
        }
    }

    private var wakeLock: PowerManager.WakeLock? = null
    private val cancelRequested = AtomicBoolean(false)

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_CANCEL_SAFELY -> {
                cancelRequested.set(true)
                writeCancelFlag()
                updateNotification("Cancelling safely at next step boundary…")
                return START_NOT_STICKY
            }
            ACTION_STOP_SESSION -> {
                releaseWakeLock()
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf()
                return START_NOT_STICKY
            }
            ACTION_UPDATE_STATUS -> {
                val statusText = intent.getStringExtra(EXTRA_STATUS_TEXT) ?: "OpenGate session active…"
                updateNotification(statusText)
                return START_NOT_STICKY
            }
        }

        cancelRequested.set(false)
        ensureChannel()
        val initialStatus = intent?.getStringExtra(EXTRA_STATUS_TEXT)
            ?: "Waiting for Sony camera over USB-C…"
        val notification = buildNotification(initialStatus)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(
                NOTIFICATION_ID,
                notification,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE
            )
        } else {
            startForeground(NOTIFICATION_ID, notification)
        }
        acquireWakeLock()
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        releaseWakeLock()
        super.onDestroy()
    }

    private fun writeCancelFlag() {
        val runDir = File(filesDir, "active_run").apply { mkdirs() }
        File(runDir, "cancel.flag").writeText("cancel\n")
    }

    private fun acquireWakeLock() {
        if (wakeLock?.isHeld == true) return
        val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
        wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "OpenGateStudio::UsbOtgSession").apply {
            acquire(15 * 60 * 1000L)
        }
    }

    private fun releaseWakeLock() {
        wakeLock?.let {
            if (it.isHeld) it.release()
        }
        wakeLock = null
    }

    private fun ensureChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val manager = getSystemService(NotificationManager::class.java)
            val channel = NotificationChannel(
                CHANNEL_ID,
                "OpenGate USB Camera Session",
                NotificationManager.IMPORTANCE_LOW
            )
            manager.createNotificationChannel(channel)
        }
    }

    private fun updateNotification(contentText: String) {
        ensureChannel()
        val manager = getSystemService(NotificationManager::class.java)
        manager.notify(NOTIFICATION_ID, buildNotification(contentText))
    }

    private fun buildNotification(contentText: String): Notification {
        val cancelIntent = Intent(this, OpenGateForegroundService::class.java).apply {
            action = ACTION_CANCEL_SAFELY
        }
        val cancelFlags = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        } else {
            PendingIntent.FLAG_UPDATE_CURRENT
        }
        val cancelPending = PendingIntent.getService(this, 1, cancelIntent, cancelFlags)

        val builder = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            Notification.Builder(this, CHANNEL_ID)
        } else {
            @Suppress("DEPRECATION")
            Notification.Builder(this)
        }
        return builder
            .setContentTitle("OpenGate Studio (Volatile RAM Only)")
            .setContentText(contentText)
            .setSmallIcon(android.R.drawable.stat_sys_data_bluetooth)
            .setOngoing(true)
            .addAction(
                Notification.Action.Builder(
                    null,
                    "Safe Cancel",
                    cancelPending
                ).build()
            )
            .build()
    }
}
