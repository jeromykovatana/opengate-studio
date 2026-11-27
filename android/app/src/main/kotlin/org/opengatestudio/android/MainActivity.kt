package org.opengatestudio.android

import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.core.content.FileProvider
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.File

private val AmberBg = Color(0xFFFFFBEB)
private val AmberBorder = Color(0xFFF59E0B)
private val AmberInk = Color(0xFF92400E)

private val SafeGreenBg = Color(0xFFECFDF5)
private val SafeGreenInk = Color(0xFF065F46)

private val AlertRedBg = Color(0xFFFEF2F2)
private val AlertRedInk = Color(0xFF991B1B)

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme {
                Surface(modifier = Modifier.fillMaxSize()) {
                    FieldCompanionScreen(
                        onKeepScreenOn = { keepOn ->
                            if (keepOn) {
                                window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                            } else {
                                window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                            }
                        }
                    )
                }
            }
        }
    }
}

private enum class CameraBodyOption(val bodyId: String, val label: String, val firmware: String) {
    ZVE1("zve1_202", "ZV-E1", "2.02"),
    A7S3("a7s3_501", "a7S III", "5.01"),
    FX3("fx3_702", "FX3", "7.02")
}

private enum class ExpressPreset(val label: String, val packs: List<String>) {
    SAFE_DAILY("Safe Daily 3:2", QuickReapplyPlanner.safeDailyPacks),
    CINEMA_FULL("Cinema Full 3:2", QuickReapplyPlanner.cinemaFullPacks)
}

private const val COMPANION_PREFS_NAME = "opengate_companion_prefs"

private fun ramAckKey(body: CameraBodyOption): String = "ack_ram_${body.bodyId}_${body.firmware}"

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun FieldCompanionScreen(onKeepScreenOn: (Boolean) -> Unit = {}) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val bridge = remember(context) { ChaquopyRuntimeBridge(context) }
    val usbBridge = remember(context) { UsbBridge(context) }
    val prefs = remember(context) {
        context.getSharedPreferences(COMPANION_PREFS_NAME, Context.MODE_PRIVATE)
    }

    var selectedBody by remember { mutableStateOf(CameraBodyOption.ZVE1) }
    var selectedPreset by remember { mutableStateOf(ExpressPreset.SAFE_DAILY) }
    var offlineMockMode by remember { mutableStateOf(false) }
    var batteryPulled10s by remember { mutableStateOf(false) }
    var inStillsMode by remember { mutableStateOf(false) }
    var confirmFirmwareAndRam by remember {
        mutableStateOf(prefs.getBoolean(ramAckKey(CameraBodyOption.ZVE1), false))
    }
    var showAdvanced by remember { mutableStateOf(false) }

    var bootstrapping by remember { mutableStateOf(true) }
    var pinsVerified by remember { mutableStateOf(false) }
    var checkedFilesCount by remember { mutableIntStateOf(0) }
    var pinErrors by remember { mutableStateOf<List<String>>(emptyList()) }
    var companionState by remember { mutableStateOf<ChaquopyRuntimeBridge.CompanionState?>(null) }

    var isRunning by remember { mutableStateOf(false) }
    var statusHeadline by remember { mutableStateOf("Verifying clean-room payload pins…") }
    var promptTitle by remember { mutableStateOf<String?>(null) }
    var promptDetail by remember { mutableStateOf<String?>(null) }
    var currentStepIndex by remember { mutableIntStateOf(0) }
    var totalStepsCount by remember { mutableIntStateOf(0) }
    var lastRunResult by remember { mutableStateOf<ChaquopyRuntimeBridge.RunResult?>(null) }
    var exportNotice by remember { mutableStateOf<String?>(null) }
    var usbDeviceSummary by remember { mutableStateOf("Scanning USB-OTG…") }
    var isFx3aBlocked by remember { mutableStateOf(false) }
    var usbWarning by remember { mutableStateOf<String?>(null) }
    val eventLog = remember { mutableStateListOf<String>() }

    DisposableEffect(isRunning) {
        onKeepScreenOn(isRunning)
        onDispose { onKeepScreenOn(false) }
    }

    fun selectBody(option: CameraBodyOption) {
        if (selectedBody != option) {
            selectedBody = option
            confirmFirmwareAndRam = prefs.getBoolean(ramAckKey(option), false)
            lastRunResult = null
        }
    }

    fun refreshUsbSummary() {
        val devs = runCatching { usbBridge.findDevices(UsbBridge.SONY_VID) }.getOrDefault(emptyList())
        val detected = QuickReapplyPlanner.detectCameraFromUsbDevices(devs)
        isFx3aBlocked = detected.isFx3aBlocked
        usbWarning = detected.warning

        if (!isRunning && !detected.isFx3aBlocked && detected.bodyId != null) {
            val matchedBody = CameraBodyOption.entries.firstOrNull { it.bodyId == detected.bodyId }
            if (matchedBody != null && matchedBody != selectedBody) {
                selectBody(matchedBody)
            }
        }

        usbDeviceSummary = if (devs.isEmpty()) {
            "No Sony USB device detected (VID 0x054C)"
        } else {
            val ids = devs.joinToString(", ") { d ->
                val pid = (d["idProduct"] as? Int) ?: 0
                val name = (d["productName"] as? String)?.trim().orEmpty()
                if (name.isNotEmpty()) "054c:%04x (%s)".format(pid, name) else "054c:%04x".format(pid)
            }
            "${devs.size} Sony USB device(s) detected: $ids"
        }
    }

    suspend fun refreshState() {
        val state = withContext(Dispatchers.IO) {
            bridge.queryState(selectedBody.bodyId, offlineMockMode)
        }
        companionState = state
        pinsVerified = state.pinsVerified
        checkedFilesCount = state.checkedFiles
        pinErrors = state.pinErrors
    }

    suspend fun runBootstrapAndQuery() {
        bootstrapping = true
        statusHeadline = "Unpacking and SHA-256 verifying opengate_kit.zip…"
        val boot = withContext(Dispatchers.IO) { bridge.bootstrapKitFromAssets() }
        pinsVerified = boot.ok
        checkedFilesCount = boot.checkedFiles
        pinErrors = boot.errors
        if (boot.ok) {
            refreshState()
            statusHeadline = "Kit verified (${boot.checkedFiles} files). Ready."
        } else {
            statusHeadline = "Kit verification failed — live USB disabled."
        }
        bootstrapping = false
        refreshUsbSummary()
    }

    LaunchedEffect(Unit) {
        runBootstrapAndQuery()
    }

    LaunchedEffect(selectedBody, offlineMockMode) {
        if (!bootstrapping && pinsVerified) {
            refreshState()
            refreshUsbSummary()
        }
    }

    LaunchedEffect(isRunning, offlineMockMode) {
        if (!isRunning && !offlineMockMode) {
            while (true) {
                refreshUsbSummary()
                delay(2500L)
            }
        }
    }

    fun launchAction(action: String, packs: List<String>? = null) {
        if (isRunning) return
        scope.launch {
            isRunning = true
            promptTitle = null
            promptDetail = null
            currentStepIndex = 0
            totalStepsCount = 0
            lastRunResult = null
            exportNotice = null
            eventLog.clear()

            if (!offlineMockMode) {
                OpenGateForegroundService.startSession(
                    context,
                    "Running ${selectedBody.label} $action over USB-OTG…"
                )
            }

            try {
                val res = withContext(Dispatchers.IO) {
                    bridge.executeRun(
                        action = action,
                        bodyId = selectedBody.bodyId,
                        offlineMock = offlineMockMode,
                        usbBridge = usbBridge,
                        firmwareConfirmed = selectedBody.firmware,
                        confirmVolatileRam = confirmFirmwareAndRam,
                        packs = packs
                    ) { ev: JSONObject ->
                        scope.launch(Dispatchers.Main) {
                            when (val kind = ev.optString("type")) {
                                "plan" -> {
                                    val stepsArr = ev.optJSONArray("steps")
                                    totalStepsCount = stepsArr?.length() ?: 1
                                    statusHeadline = "Planned ${totalStepsCount} step(s) for ${selectedBody.label} $action"
                                    eventLog.add("PLAN: $action (${totalStepsCount} steps)")
                                }
                                "wait_drive" -> {
                                    promptTitle = ev.optString("title")
                                    promptDetail = ev.optString("detail")
                                    currentStepIndex = ev.optInt("step_index", currentStepIndex)
                                    val tot = ev.optInt("total_steps", totalStepsCount)
                                    if (tot > 0) totalStepsCount = tot
                                    statusHeadline = promptTitle ?: "Waiting for USB camera…"
                                    if (!offlineMockMode) {
                                        OpenGateForegroundService.updateStatus(context, statusHeadline)
                                    }
                                    eventLog.add("PROMPT: $statusHeadline")
                                }
                                "wait_movie_replug" -> {
                                    promptTitle = ev.optString("title", "Switch camera to Movie mode")
                                    promptDetail = ev.optString("detail")
                                    statusHeadline = promptTitle ?: "Switch to Movie mode and replug USB-C"
                                    if (!offlineMockMode) {
                                        OpenGateForegroundService.updateStatus(context, statusHeadline)
                                    }
                                    eventLog.add("MOVIE REPLUG: $statusHeadline")
                                }
                                "step_start" -> {
                                    promptTitle = null
                                    promptDetail = null
                                    currentStepIndex = ev.optInt("step_index", currentStepIndex)
                                    val tot = ev.optInt("total_steps", totalStepsCount)
                                    if (tot > 0) totalStepsCount = tot
                                    val sid = ev.optString("step_id")
                                    val summary = ev.optString("summary")
                                    statusHeadline = "Step $currentStepIndex/$totalStepsCount: $sid — $summary"
                                    if (!offlineMockMode) {
                                        OpenGateForegroundService.updateStatus(context, statusHeadline)
                                    }
                                    eventLog.add("START $sid: $summary")
                                }
                                "step_done" -> {
                                    val sid = ev.optString("step_id")
                                    val outcome = ev.optString("outcome", "DONE")
                                    eventLog.add("DONE $sid: $outcome")
                                }
                                "closing_dump_start" -> {
                                    promptTitle = null
                                    promptDetail = null
                                    val ck = ev.optString("closing_kind")
                                    statusHeadline = "Running closing verification ($ck)…"
                                    eventLog.add("CLOSING START: $ck")
                                }
                                "closing_dump_done" -> {
                                    val verdict = ev.optString("verdict")
                                    eventLog.add("CLOSING DONE: $verdict")
                                }
                                "complete" -> {
                                    promptTitle = null
                                    promptDetail = null
                                    statusHeadline = ev.optString("verdict", "Completed")
                                    eventLog.add("COMPLETE: $statusHeadline")
                                }
                                "cancelled" -> {
                                    promptTitle = null
                                    promptDetail = null
                                    statusHeadline = ev.optString("message", "Cancelled safely")
                                    eventLog.add("CANCELLED: $statusHeadline")
                                }
                                "error" -> {
                                    val msg = ev.optString("message", "Error")
                                    statusHeadline = msg
                                    eventLog.add("ERROR: $msg")
                                }
                                else -> {
                                    eventLog.add(kind.uppercase())
                                }
                            }
                        }
                    }
                }
                lastRunResult = res
                if (res.ok && res.verdict.isNotEmpty()) {
                    statusHeadline = res.verdict
                } else if (!res.ok && !res.error.isNullOrEmpty()) {
                    statusHeadline = res.error
                }
                refreshState()
                refreshUsbSummary()
            } finally {
                if (!offlineMockMode) {
                    OpenGateForegroundService.stopSession(context)
                }
                isRunning = false
            }
        }
    }

    val decision = companionState?.decision ?: if (!pinsVerified) {
        QuickReapplyDecision.BlockedPinsUnverified
    } else {
        QuickReapplyDecision.RunPreflightThenSafeDailyApply
    }
    val checklistReady = batteryPulled10s && inStillsMode
    val liveUsbAllowed = !isFx3aBlocked || offlineMockMode
    val expressEnabled = !bootstrapping && !isRunning && (!pinsVerified || (confirmFirmwareAndRam && liveUsbAllowed))
    val expressPutbackEnabled = !bootstrapping && !isRunning && pinsVerified && confirmFirmwareAndRam && liveUsbAllowed

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("OpenGate Field Companion") }
            )
        }
    ) { padding ->
        Column(
            modifier = Modifier
                .padding(padding)
                .padding(16.dp)
                .verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            // Pin verification status badge
            Card(
                colors = CardDefaults.cardColors(
                    containerColor = if (pinsVerified) SafeGreenBg else AlertRedBg
                ),
                modifier = Modifier.fillMaxWidth()
            ) {
                Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text(
                        text = if (bootstrapping) {
                            "Verifying Clean-Room Kit Pins…"
                        } else if (pinsVerified) {
                            "Clean-Room Kit Verified ($checkedFilesCount SHA-256 pinned files)"
                        } else {
                            "Kit Verification Failed — Live USB Blocked"
                        },
                        color = if (pinsVerified) SafeGreenInk else AlertRedInk,
                        fontWeight = FontWeight.SemiBold,
                        style = MaterialTheme.typography.bodyMedium
                    )
                    if (pinErrors.isNotEmpty()) {
                        Text(
                            text = pinErrors.joinToString("\n"),
                            color = AlertRedInk,
                            style = MaterialTheme.typography.bodySmall
                        )
                    }
                }
            }

            // Unsupported FX3A hardware block banner
            if (isFx3aBlocked) {
                Card(
                    colors = CardDefaults.cardColors(containerColor = AlertRedBg),
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        Text(
                            text = "Unsupported Camera Detected — Live USB Disabled",
                            color = AlertRedInk,
                            fontWeight = FontWeight.Bold,
                            style = MaterialTheme.typography.bodyMedium
                        )
                        Text(
                            text = usbWarning ?: "ILME-FX3A is not supported by FX3 7.02 kits",
                            color = AlertRedInk,
                            style = MaterialTheme.typography.bodySmall
                        )
                    }
                }
            }

            // Body selector
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                CameraBodyOption.entries.forEach { option ->
                    FilterChip(
                        selected = selectedBody == option,
                        enabled = !isRunning,
                        onClick = { selectBody(option) },
                        label = { Text("${option.label} ${option.firmware}") }
                    )
                }
            }

            // Mode toggle (Amber Offline Simulation vs Live USB-OTG)
            Card(
                colors = CardDefaults.cardColors(
                    containerColor = if (offlineMockMode) AmberBg else MaterialTheme.colorScheme.surfaceVariant
                ),
                border = if (offlineMockMode) BorderStroke(1.dp, AmberBorder) else null,
                modifier = Modifier.fillMaxWidth()
            ) {
                Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.SpaceBetween
                    ) {
                        Column(modifier = Modifier.weight(1f)) {
                            Text(
                                text = if (offlineMockMode) {
                                    "OFFLINE SIMULATION MODE (AMBER)"
                                } else {
                                    "Live USB-OTG Mode (Sony VID 0x054C)"
                                },
                                color = if (offlineMockMode) AmberInk else MaterialTheme.colorScheme.onSurface,
                                fontWeight = FontWeight.Bold,
                                style = MaterialTheme.typography.labelLarge
                            )
                            Text(
                                text = if (offlineMockMode) {
                                    "Simulated dry-run only — mock results NEVER unlock live USB apply."
                                } else {
                                    usbDeviceSummary
                                },
                                color = if (offlineMockMode) AmberInk else MaterialTheme.colorScheme.onSurfaceVariant,
                                style = MaterialTheme.typography.bodySmall
                            )
                        }
                        Switch(
                            checked = offlineMockMode,
                            enabled = !isRunning,
                            onCheckedChange = { offlineMockMode = it }
                        )
                    }
                    if (!offlineMockMode) {
                        OutlinedButton(
                            onClick = { refreshUsbSummary() },
                            enabled = !isRunning
                        ) {
                            Text("Refresh USB-OTG Scan")
                        }
                    }
                }
            }

            // Main 1-Tap Express Apply & planner card
            Card(modifier = Modifier.fillMaxWidth()) {
                Column(
                    modifier = Modifier.padding(16.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp)
                ) {
                    Text(
                        text = when (decision) {
                            QuickReapplyDecision.BlockedPinsUnverified ->
                                "Kit Verification Required"
                            QuickReapplyDecision.RunRecoveryPreflightFirst ->
                                "1-Tap Express Ready (${selectedBody.label} — Recovery Recommended)"
                            QuickReapplyDecision.AlreadyApplied ->
                                "Open-Gate 3:2 Active (${selectedBody.label})"
                            else ->
                                if (offlineMockMode) "1-Tap Express Simulation (${selectedBody.label})"
                                else "1-Tap Express Open-Gate (${selectedBody.label})"
                        },
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.SemiBold
                    )

                    Text(
                        text = "Volatile RAM only — zero flash or SD card writes. Fused Q19/F19 verifies stock RAM & mixed power-switch atomically before writing (~6s, 1 USB session).",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )

                    companionState?.latestSession?.let { sess ->
                        Text(
                            text = "Last session: mode=${sess.mode ?: "?"}, kind=${sess.kind ?: "?"}, state=${sess.state}, ready=${sess.ready}",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }

                    // Express preset selector
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        ExpressPreset.entries.forEach { preset ->
                            FilterChip(
                                selected = selectedPreset == preset,
                                enabled = !isRunning,
                                onClick = { selectedPreset = preset },
                                label = { Text(preset.label) }
                            )
                        }
                    }

                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Checkbox(
                            checked = confirmFirmwareAndRam,
                            enabled = !isRunning,
                            onCheckedChange = { checked ->
                                confirmFirmwareAndRam = checked
                                prefs.edit().putBoolean(ramAckKey(selectedBody), checked).apply()
                            }
                        )
                        Text("Confirm firmware ${selectedBody.firmware} & volatile RAM only (remembered)")
                    }

                    Spacer(modifier = Modifier.height(2.dp))

                    val primaryLabel = when {
                        !pinsVerified -> "Re-Verify Payload Integrity"
                        offlineMockMode -> "Simulate 1-Tap ${selectedPreset.label} (Mock)"
                        else -> "Apply ${selectedPreset.label} (~6s, 1-Tap)"
                    }

                    Button(
                        onClick = {
                            if (!pinsVerified) {
                                scope.launch { runBootstrapAndQuery() }
                            } else {
                                launchAction("express-apply", selectedPreset.packs)
                            }
                        },
                        enabled = expressEnabled,
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Text(primaryLabel)
                    }

                    OutlinedButton(
                        onClick = { launchAction("express-putback", selectedPreset.packs) },
                        enabled = expressPutbackEnabled,
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Text("Restore Stock RAM (1-Tap)")
                    }

                    if (isRunning) {
                        Button(
                            onClick = { OpenGateForegroundService.requestSafeCancel(context) },
                            colors = ButtonDefaults.buttonColors(containerColor = AlertRedInk),
                            modifier = Modifier.fillMaxWidth()
                        ) {
                            Text("Cancel Safely (Between Steps)")
                        }
                    }

                    TextButton(
                        onClick = { showAdvanced = !showAdvanced },
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Text(
                            if (showAdvanced) "Hide Advanced & Diagnostics"
                            else "Advanced & Diagnostics"
                        )
                    }

                    if (showAdvanced) {
                        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Checkbox(
                                    checked = batteryPulled10s,
                                    enabled = !isRunning,
                                    onCheckedChange = { batteryPulled10s = it }
                                )
                                Text("Pulled battery >= 10 seconds (cold RAM baseline)")
                            }

                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Checkbox(
                                    checked = inStillsMode,
                                    enabled = !isRunning,
                                    onCheckedChange = { inStillsMode = it }
                                )
                                Text("Camera is in Stills mode (Mass Storage)")
                            }

                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.spacedBy(8.dp)
                            ) {
                                OutlinedButton(
                                    onClick = { launchAction("preflight") },
                                    enabled = !isRunning && pinsVerified && liveUsbAllowed,
                                    modifier = Modifier.weight(1f)
                                ) {
                                    Text("Check Camera (Read-Only)")
                                }
                                OutlinedButton(
                                    onClick = { launchAction("dump") },
                                    enabled = !isRunning && pinsVerified && liveUsbAllowed,
                                    modifier = Modifier.weight(1f)
                                ) {
                                    Text("Read-Only Dump")
                                }
                            }

                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.spacedBy(8.dp)
                            ) {
                                OutlinedButton(
                                    onClick = { launchAction("apply", selectedPreset.packs) },
                                    enabled = !isRunning && pinsVerified && checklistReady && confirmFirmwareAndRam && liveUsbAllowed,
                                    modifier = Modifier.weight(1f)
                                ) {
                                    Text("Legacy Multi-Step Apply")
                                }
                                OutlinedButton(
                                    onClick = { launchAction("putback", selectedPreset.packs) },
                                    enabled = !isRunning && pinsVerified && checklistReady && confirmFirmwareAndRam && liveUsbAllowed,
                                    modifier = Modifier.weight(1f)
                                ) {
                                    Text("Legacy Putback")
                                }
                            }

                            OutlinedButton(
                                onClick = {
                                    scope.launch {
                                        val exp = withContext(Dispatchers.IO) { bridge.exportBundle() }
                                        if (exp.ok) {
                                            val file = File(exp.zipPath)
                                            val uri = FileProvider.getUriForFile(
                                                context,
                                                "${context.packageName}.fileprovider",
                                                file
                                            )
                                            val shareIntent = Intent(Intent.ACTION_SEND).apply {
                                                type = "application/zip"
                                                putExtra(Intent.EXTRA_STREAM, uri)
                                                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                                            }
                                            exportNotice = "Exported ${exp.exportedCount} safe file(s); skipped ${exp.skippedPrivate} private file(s)."
                                            context.startActivity(Intent.createChooser(shareIntent, "Share OpenGate Session Bundle"))
                                        } else {
                                            exportNotice = "Export failed."
                                        }
                                    }
                                },
                                enabled = !isRunning,
                                modifier = Modifier.fillMaxWidth()
                            ) {
                                Text("Export Session Bundle (Excludes Private Dumps)")
                            }

                            exportNotice?.let {
                                Text(
                                    text = it,
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant
                                )
                            }
                        }
                    }
                }
            }

            // Live progress / prompt card
            if (isRunning || lastRunResult != null || eventLog.isNotEmpty()) {
                Card(modifier = Modifier.fillMaxWidth()) {
                    Column(
                        modifier = Modifier.padding(16.dp),
                        verticalArrangement = Arrangement.spacedBy(8.dp)
                    ) {
                        Text(
                            text = statusHeadline,
                            style = MaterialTheme.typography.titleSmall,
                            fontWeight = FontWeight.SemiBold
                        )
                        if (isRunning) {
                            if (totalStepsCount > 0) {
                                LinearProgressIndicator(
                                    progress = { (currentStepIndex.toFloat() / totalStepsCount.toFloat()).coerceIn(0f, 1f) },
                                    modifier = Modifier.fillMaxWidth()
                                )
                            } else {
                                LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
                            }
                        }
                        if (promptTitle != null || promptDetail != null) {
                            Card(
                                colors = CardDefaults.cardColors(containerColor = AmberBg),
                                border = BorderStroke(1.dp, AmberBorder),
                                modifier = Modifier.fillMaxWidth()
                            ) {
                                Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                                    promptTitle?.let {
                                        Text(it, color = AmberInk, fontWeight = FontWeight.Bold)
                                    }
                                    promptDetail?.let {
                                        Text(it, color = AmberInk, style = MaterialTheme.typography.bodySmall)
                                    }
                                }
                            }
                        }
                        if (lastRunResult?.leftBehind == true) {
                            Card(
                                colors = CardDefaults.cardColors(containerColor = AlertRedBg),
                                modifier = Modifier.fillMaxWidth()
                            ) {
                                Text(
                                    text = "Helper /tmp/jiritsu/libJit.so may remain on the camera service partition. Pull the camera battery for >= 10 seconds to restore clean stock.",
                                    color = AlertRedInk,
                                    style = MaterialTheme.typography.bodySmall,
                                    modifier = Modifier.padding(12.dp)
                                )
                            }
                        }
                        if (eventLog.isNotEmpty()) {
                            Text(
                                text = eventLog.takeLast(8).joinToString("\n"),
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                    }
                }
            }
        }
    }
}
