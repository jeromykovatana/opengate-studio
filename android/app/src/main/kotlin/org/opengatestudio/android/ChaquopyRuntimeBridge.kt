package org.opengatestudio.android

import android.content.Context
import com.chaquo.python.Kwarg
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Kotlin <-> Chaquopy bridge calling `opengate_android.live_runner` in-process.
 */
class ChaquopyRuntimeBridge(context: Context) {
    companion object {
        private const val KIT_ASSET_NAME = "opengate_kit.zip"

        @Volatile
        private var pythonInitialized = false

        @Synchronized
        private fun ensurePythonStarted(appContext: Context) {
            if (!pythonInitialized && !Python.isStarted()) {
                Python.start(AndroidPlatform(appContext))
                pythonInitialized = true
            }
        }
    }

    interface CompanionEventListener {
        fun onEvent(eventJson: String)
    }

    data class BootstrapResult(
        val ok: Boolean,
        val checkedFiles: Int,
        val errors: List<String>
    )

    data class CompanionState(
        val ok: Boolean,
        val pinsVerified: Boolean,
        val checkedFiles: Int,
        val pinErrors: List<String>,
        val bodyId: String,
        val offlineMock: Boolean,
        val decision: QuickReapplyDecision,
        val packs: List<String>,
        val latestSession: SessionSnapshot?,
        val leftBehind: Boolean,
        val livePreflightValid: Boolean,
        val livePreflightReason: String,
        val error: String? = null
    )

    data class RunResult(
        val ok: Boolean,
        val cancelled: Boolean,
        val mode: String,
        val action: String,
        val bodyId: String,
        val sessionId: String?,
        val verdict: String,
        val state: String,
        val ready: Boolean,
        val verified: Boolean,
        val error: String?,
        val leftBehind: Boolean
    )

    data class ExportBundleResult(
        val ok: Boolean,
        val exportedCount: Int,
        val skippedPrivate: Int,
        val zipPath: String
    )

    private val appContext: Context = context.applicationContext
    val unpackDir: File = File(appContext.filesDir, "opengate_kit")
    val sessionsDir: File = File(appContext.filesDir, "sessions")
    val exportsDir: File = File(appContext.filesDir, "exports")
    val activeRunDir: File = File(appContext.filesDir, "active_run")
    val cancelFile: File = File(activeRunDir, "cancel.flag")
    private val stagedKitZip: File = File(appContext.filesDir, KIT_ASSET_NAME)

    private fun liveRunner() = run {
        ensurePythonStarted(appContext)
        Python.getInstance().getModule("opengate_android.live_runner")
    }

    fun bootstrapKitFromAssets(): BootstrapResult {
        appContext.assets.open(KIT_ASSET_NAME).use { input ->
            stagedKitZip.outputStream().use { output ->
                input.copyTo(output)
            }
        }
        val raw = liveRunner()
            .callAttr("bootstrap_kit", stagedKitZip.absolutePath, unpackDir.absolutePath)
            .toString()
        val obj = JSONObject(raw)
        return BootstrapResult(
            ok = obj.optBoolean("ok", false),
            checkedFiles = obj.optInt("checked_files", 0),
            errors = jsonStringList(obj.optJSONArray("errors"))
        )
    }

    fun queryState(bodyId: String, offlineMock: Boolean): CompanionState {
        sessionsDir.mkdirs()
        val raw = liveRunner()
            .callAttr(
                "query_companion_state",
                unpackDir.absolutePath,
                sessionsDir.absolutePath,
                bodyId,
                offlineMock
            )
            .toString()
        val obj = JSONObject(raw)
        val pinsVerified = obj.optBoolean("pins_verified", false)
        val packs = jsonStringList(obj.optJSONArray("packs"))
        val latestObj = obj.optJSONObject("latest_session")
        val latestSnapshot = latestObj?.takeIf { it.optBoolean("found", false) }?.let {
            SessionSnapshot(
                ok = it.optBoolean("ok", false),
                found = true,
                bodyId = it.optString("body_id", bodyId),
                kind = it.optString("kind").ifEmpty { null },
                mode = it.optString("mode").ifEmpty { null },
                ready = it.optBoolean("ready", false),
                verified = if (it.has("verified") && !it.isNull("verified")) it.optBoolean("verified") else null,
                state = it.optString("state", "unknown")
            )
        }
        return CompanionState(
            ok = obj.optBoolean("ok", false),
            pinsVerified = pinsVerified,
            checkedFiles = obj.optInt("checked_files", 0),
            pinErrors = jsonStringList(obj.optJSONArray("pin_errors")),
            bodyId = obj.optString("body_id", bodyId),
            offlineMock = obj.optBoolean("offline_mock", offlineMock),
            decision = parseDecision(obj.optString("decision"), packs),
            packs = packs,
            latestSession = latestSnapshot,
            leftBehind = obj.optBoolean("left_behind", false),
            livePreflightValid = obj.optBoolean("live_preflight_valid", false),
            livePreflightReason = obj.optString("live_preflight_reason", ""),
            error = obj.optString("error").ifEmpty { null }
        )
    }

    fun executeRun(
        action: String,
        bodyId: String,
        offlineMock: Boolean,
        usbBridge: UsbBridge?,
        firmwareConfirmed: String?,
        confirmVolatileRam: Boolean,
        packs: List<String>? = null,
        onEvent: (JSONObject) -> Unit
    ): RunResult {
        sessionsDir.mkdirs()
        activeRunDir.mkdirs()
        if (cancelFile.exists()) {
            cancelFile.delete()
        }

        val listener = object : CompanionEventListener {
            override fun onEvent(eventJson: String) {
                runCatching { JSONObject(eventJson) }.onSuccess { onEvent(it) }
            }
        }

        val args = mutableListOf<Any?>(
            unpackDir.absolutePath,
            sessionsDir.absolutePath,
            action,
            bodyId,
            offlineMock,
            if (offlineMock) null else usbBridge,
            firmwareConfirmed,
            confirmVolatileRam,
            cancelFile.absolutePath,
            listener
        )
        if (!packs.isNullOrEmpty()) {
            args.add(Kwarg("packs", packs.joinToString(",")))
        }

        val raw = liveRunner().callAttr("execute_companion_run", *args.toTypedArray()).toString()
        val obj = JSONObject(raw)
        return RunResult(
            ok = obj.optBoolean("ok", false),
            cancelled = obj.optBoolean("cancelled", false),
            mode = obj.optString("mode", if (offlineMock) "mock" else "live_usb"),
            action = obj.optString("action", action),
            bodyId = obj.optString("body_id", bodyId),
            sessionId = obj.optString("session_id").ifEmpty { null },
            verdict = obj.optString("verdict", ""),
            state = obj.optString("state", "unknown"),
            ready = obj.optBoolean("ready", false),
            verified = obj.optBoolean("verified", false),
            error = obj.optString("error").ifEmpty { null },
            leftBehind = obj.optBoolean("left_behind", false)
        )
    }

    fun exportBundle(): ExportBundleResult {
        exportsDir.mkdirs()
        val stamp = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(Date())
        val outZip = File(exportsDir, "opengate_session_bundle_$stamp.zip")
        val raw = liveRunner()
            .callAttr("export_companion_bundle", sessionsDir.absolutePath, outZip.absolutePath)
            .toString()
        val obj = JSONObject(raw)
        return ExportBundleResult(
            ok = obj.optBoolean("ok", false),
            exportedCount = obj.optInt("exported_count", 0),
            skippedPrivate = obj.optInt("skipped_private", 0),
            zipPath = obj.optString("zip_path", outZip.absolutePath)
        )
    }

    private fun parseDecision(raw: String, packs: List<String>): QuickReapplyDecision {
        return when (raw) {
            "blocked_pins_unverified" -> QuickReapplyDecision.BlockedPinsUnverified
            "run_recovery_preflight_first" -> QuickReapplyDecision.RunRecoveryPreflightFirst
            "ready_for_safe_daily_apply" -> QuickReapplyDecision.ReadyForSafeDailyApply(
                packs.ifEmpty { QuickReapplyPlanner.safeDailyPacks }
            )
            "already_applied" -> QuickReapplyDecision.AlreadyApplied
            else -> QuickReapplyDecision.RunPreflightThenSafeDailyApply
        }
    }

    private fun jsonStringList(arr: JSONArray?): List<String> {
        if (arr == null) return emptyList()
        return buildList(arr.length()) {
            for (i in 0 until arr.length()) {
                val item = arr.optString(i, "")
                if (item.isNotEmpty()) add(item)
            }
        }
    }
}
