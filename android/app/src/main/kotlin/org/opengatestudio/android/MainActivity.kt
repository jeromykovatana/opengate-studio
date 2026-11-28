package org.opengatestudio.android

import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Build
import androidx.compose.material.icons.rounded.Check
import androidx.compose.material.icons.rounded.Computer
import androidx.compose.material.icons.rounded.KeyboardArrowDown
import androidx.compose.material.icons.rounded.Movie
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
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
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
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

private enum class ExpressPreset(
    val label: String,
    val subtitle: String,
    val packs: List<String>
) {
    SAFE_DAILY("Safe Daily 3:2", "MP4 · Gyro · LCD", QuickReapplyPlanner.safeDailyPacks),
    CINEMA_FULL("Cinema Full 3:2", "HDMI · High-Bitrate", QuickReapplyPlanner.cinemaFullPacks)
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
    var bodyMenuExpanded by remember { mutableStateOf(false) }
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
    var usbDetectedCount by remember { mutableIntStateOf(0) }
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
        usbDetectedCount = devs.size

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
                title = {
                    Box {
                        Row(
                            modifier = Modifier
                                .clickable(enabled = !isRunning) { bodyMenuExpanded = true }
                                .padding(vertical = 6.dp, horizontal = 4.dp),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(4.dp)
                        ) {
                            Text(
                                text = "${selectedBody.label} ${selectedBody.firmware}",
                                style = MaterialTheme.typography.titleLarge,
                                fontWeight = FontWeight.Medium
                            )
                            Icon(
                                imageVector = Icons.Rounded.KeyboardArrowDown,
                                contentDescription = "Select camera body",
                                modifier = Modifier.size(20.dp)
                            )
                        }
                        DropdownMenu(
                            expanded = bodyMenuExpanded,
                            onDismissRequest = { bodyMenuExpanded = false }
                        ) {
                            CameraBodyOption.entries.forEach { option ->
                                DropdownMenuItem(
                                    text = { Text("${option.label} ${option.firmware}") },
                                    trailingIcon = if (selectedBody == option) {
                                        {
                                            Icon(
                                                imageVector = Icons.Rounded.Check,
                                                contentDescription = "Selected",
                                                tint = MaterialTheme.colorScheme.primary
                                            )
                                        }
                                    } else null,
                                    onClick = {
                                        selectBody(option)
                                        bodyMenuExpanded = false
                                    }
                                )
                            }
                        }
                    }
                },
                actions = {
                    val pillBg = when {
                        bootstrapping -> MaterialTheme.colorScheme.surfaceContainer
                        pinsVerified -> SafeGreenBg
                        else -> AlertRedBg
                    }
                    val pillInk = when {
                        bootstrapping -> MaterialTheme.colorScheme.onSurfaceVariant
                        pinsVerified -> SafeGreenInk
                        else -> AlertRedInk
                    }
                    val pillLabel = when {
                        bootstrapping -> "Checking…"
                        pinsVerified -> "✓ Verified"
                        else -> "Kit Error"
                    }
                    Surface(
                        shape = RoundedCornerShape(999.dp),
                        color = pillBg
                    ) {
                        Text(
                            text = pillLabel,
                            color = pillInk,
                            fontWeight = FontWeight.SemiBold,
                            style = MaterialTheme.typography.labelMedium,
                            modifier = Modifier.padding(horizontal = 10.dp, vertical = 5.dp)
                        )
                    }
                    Spacer(modifier = Modifier.width(8.dp))
                    Surface(
                        onClick = { showAdvanced = !showAdvanced },
                        shape = CircleShape,
                        color = if (showAdvanced) {
                            MaterialTheme.colorScheme.secondaryContainer
                        } else {
                            MaterialTheme.colorScheme.surfaceContainer
                        },
                        modifier = Modifier.size(36.dp)
                    ) {
                        Box(
                            modifier = Modifier.fillMaxSize(),
                            contentAlignment = Alignment.Center
                        ) {
                            Icon(
                                imageVector = Icons.Rounded.Build,
                                contentDescription = "Advanced and diagnostics",
                                tint = if (showAdvanced) {
                                    MaterialTheme.colorScheme.onSecondaryContainer
                                } else {
                                    MaterialTheme.colorScheme.onSurfaceVariant
                                },
                                modifier = Modifier.size(18.dp)
                            )
                        }
                    }
                    Spacer(modifier = Modifier.width(12.dp))
                }
            )
        },
        bottomBar = {
            Surface(
                shape = RoundedCornerShape(topStart = 20.dp, topEnd = 20.dp),
                color = MaterialTheme.colorScheme.surface,
                tonalElevation = 2.dp,
                shadowElevation = 6.dp,
                border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
                modifier = Modifier.fillMaxWidth()
            ) {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .navigationBarsPadding()
                        .padding(horizontal = 16.dp, vertical = 12.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp)
                ) {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clickable(enabled = !isRunning) {
                                val checked = !confirmFirmwareAndRam
                                confirmFirmwareAndRam = checked
                                prefs.edit().putBoolean(ramAckKey(selectedBody), checked).apply()
                            },
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Checkbox(
                            checked = confirmFirmwareAndRam,
                            enabled = !isRunning,
                            onCheckedChange = { checked ->
                                confirmFirmwareAndRam = checked
                                prefs.edit().putBoolean(ramAckKey(selectedBody), checked).apply()
                            }
                        )
                        Text(
                            text = "FW ${selectedBody.firmware} · Volatile RAM only (battery >= 10s resets)",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }

                    if (isRunning) {
                        Button(
                            onClick = { OpenGateForegroundService.requestSafeCancel(context) },
                            colors = ButtonDefaults.buttonColors(containerColor = AlertRedInk),
                            modifier = Modifier
                                .fillMaxWidth()
                                .height(52.dp)
                        ) {
                            Text(
                                text = "Cancel Safely (Between Steps)",
                                style = MaterialTheme.typography.titleSmall,
                                fontWeight = FontWeight.SemiBold
                            )
                        }
                    } else {
                        val primaryLabel = when {
                            !pinsVerified -> "Re-Verify Payload Integrity"
                            offlineMockMode -> "Simulate ${selectedPreset.label} (Mock)"
                            else -> "Apply ${selectedPreset.label} (~6s)"
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
                            modifier = Modifier
                                .fillMaxWidth()
                                .height(52.dp)
                        ) {
                            Text(
                                text = primaryLabel,
                                style = MaterialTheme.typography.titleSmall,
                                fontWeight = FontWeight.SemiBold
                            )
                        }
                    }
                }
            }
        }
    ) { padding ->
        Column(
            modifier = Modifier
                .padding(padding)
                .padding(horizontal = 16.dp, vertical = 12.dp)
                .verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            // Conditional kit pin failure alert
            if (!bootstrapping && !pinsVerified) {
                Card(
                    colors = CardDefaults.cardColors(containerColor = AlertRedBg),
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Column(
                        modifier = Modifier.padding(12.dp),
                        verticalArrangement = Arrangement.spacedBy(4.dp)
                    ) {
                        Text(
                            text = "Kit Verification Failed — Live USB Blocked",
                            color = AlertRedInk,
                            fontWeight = FontWeight.Bold,
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
            }

            // Conditional unsupported FX3A hardware block banner
            if (isFx3aBlocked) {
                Card(
                    colors = CardDefaults.cardColors(containerColor = AlertRedBg),
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Column(
                        modifier = Modifier.padding(12.dp),
                        verticalArrangement = Arrangement.spacedBy(4.dp)
                    ) {
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

            // Conditional Amber offline simulation warning
            if (offlineMockMode) {
                Card(
                    colors = CardDefaults.cardColors(containerColor = AmberBg),
                    border = BorderStroke(1.dp, AmberBorder),
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Text(
                        text = "OFFLINE SIMULATION MODE — Simulated dry-run only; mock results never unlock live USB apply.",
                        color = AmberInk,
                        fontWeight = FontWeight.SemiBold,
                        style = MaterialTheme.typography.bodySmall,
                        modifier = Modifier.padding(12.dp)
                    )
                }
            }

            // Conditional state / recovery notice
            if (decision == QuickReapplyDecision.AlreadyApplied ||
                decision == QuickReapplyDecision.RunRecoveryPreflightFirst
            ) {
                val recovery = decision == QuickReapplyDecision.RunRecoveryPreflightFirst
                Card(
                    colors = CardDefaults.cardColors(
                        containerColor = if (recovery) AmberBg else SafeGreenBg
                    ),
                    border = if (recovery) BorderStroke(1.dp, AmberBorder) else null,
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Text(
                        text = if (recovery) {
                            "Recovery Preflight Recommended (${selectedBody.label})"
                        } else {
                            "Open-Gate 3:2 Active (${selectedBody.label})"
                        },
                        color = if (recovery) AmberInk else SafeGreenInk,
                        fontWeight = FontWeight.SemiBold,
                        style = MaterialTheme.typography.bodySmall,
                        modifier = Modifier.padding(12.dp)
                    )
                }
            }

            // Live progress / prompt card placed above controls so camera replug prompts appear immediately
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
                                Column(
                                    modifier = Modifier.padding(12.dp),
                                    verticalArrangement = Arrangement.spacedBy(4.dp)
                                ) {
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

            // 2x2 Quick-Tap Tile Grid
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(10.dp)
                ) {
                    ExpressPreset.entries.forEach { preset ->
                        val isSelected = selectedPreset == preset
                        QuickTapTile(
                            title = preset.label,
                            subtitle = preset.subtitle,
                            icon = if (isSelected) Icons.Rounded.Check else Icons.Rounded.Movie,
                            iconTint = if (isSelected) {
                                MaterialTheme.colorScheme.primary
                            } else {
                                MaterialTheme.colorScheme.onSurfaceVariant
                            },
                            containerColor = if (isSelected) {
                                MaterialTheme.colorScheme.secondaryContainer
                            } else {
                                MaterialTheme.colorScheme.surfaceContainer
                            },
                            contentColor = if (isSelected) {
                                MaterialTheme.colorScheme.onSecondaryContainer
                            } else {
                                MaterialTheme.colorScheme.onSurface
                            },
                            subtitleColor = MaterialTheme.colorScheme.onSurfaceVariant,
                            border = if (isSelected) {
                                BorderStroke(2.dp, MaterialTheme.colorScheme.primary)
                            } else null,
                            enabled = !isRunning,
                            modifier = Modifier.weight(1f),
                            onClick = { selectedPreset = preset }
                        )
                    }
                }

                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(10.dp)
                ) {
                    val usbContainer = when {
                        isFx3aBlocked -> AlertRedBg
                        usbDetectedCount > 0 -> SafeGreenBg
                        else -> MaterialTheme.colorScheme.surfaceContainer
                    }
                    val usbContentInk = when {
                        isFx3aBlocked -> AlertRedInk
                        usbDetectedCount > 0 -> SafeGreenInk
                        else -> MaterialTheme.colorScheme.onSurface
                    }
                    val usbSubtitleInk = when {
                        isFx3aBlocked -> AlertRedInk
                        usbDetectedCount > 0 -> SafeGreenInk
                        else -> MaterialTheme.colorScheme.onSurfaceVariant
                    }
                    val usbSubtitle = when {
                        isFx3aBlocked -> "FX3A blocked"
                        usbDetectedCount > 0 -> "$usbDetectedCount Sony USB"
                        else -> "Tap to scan"
                    }

                    QuickTapTile(
                        title = "USB-OTG",
                        subtitle = usbSubtitle,
                        icon = Icons.Rounded.Refresh,
                        iconTint = usbContentInk,
                        containerColor = usbContainer,
                        contentColor = usbContentInk,
                        subtitleColor = usbSubtitleInk,
                        border = null,
                        enabled = !isRunning,
                        modifier = Modifier.weight(1f),
                        onClick = { refreshUsbSummary() }
                    )

                    QuickTapTile(
                        title = "Simulation",
                        subtitle = if (offlineMockMode) "On · Amber Mock" else "Off · Live USB",
                        icon = Icons.Rounded.Computer,
                        iconTint = if (offlineMockMode) AmberInk else MaterialTheme.colorScheme.onSurfaceVariant,
                        containerColor = if (offlineMockMode) AmberBg else MaterialTheme.colorScheme.surfaceContainer,
                        contentColor = if (offlineMockMode) AmberInk else MaterialTheme.colorScheme.onSurface,
                        subtitleColor = if (offlineMockMode) AmberInk else MaterialTheme.colorScheme.onSurfaceVariant,
                        border = if (offlineMockMode) BorderStroke(1.5.dp, AmberBorder) else null,
                        enabled = !isRunning,
                        modifier = Modifier.weight(1f),
                        onClick = { offlineMockMode = !offlineMockMode }
                    )
                }
            }

            // Two side-by-side outlined utility pills
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(10.dp)
            ) {
                OutlinedButton(
                    onClick = { launchAction("express-putback", selectedPreset.packs) },
                    enabled = expressPutbackEnabled,
                    modifier = Modifier.weight(1f)
                ) {
                    Text(
                        text = "Restore Stock",
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis
                    )
                }
                OutlinedButton(
                    onClick = { showAdvanced = !showAdvanced },
                    modifier = Modifier.weight(1f)
                ) {
                    Text(
                        text = if (showAdvanced) "Hide Advanced" else "Advanced & Logs",
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis
                    )
                }
            }

            // Expandable Advanced & Diagnostics card
            if (showAdvanced) {
                Card(modifier = Modifier.fillMaxWidth()) {
                    Column(
                        modifier = Modifier.padding(16.dp),
                        verticalArrangement = Arrangement.spacedBy(10.dp)
                    ) {
                        Text(
                            text = "Advanced & Diagnostics",
                            style = MaterialTheme.typography.titleSmall,
                            fontWeight = FontWeight.SemiBold
                        )
                        Text(
                            text = "Kit pins: $checkedFilesCount SHA-256 pinned files · USB: $usbDeviceSummary",
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
    }
}

@Composable
private fun QuickTapTile(
    title: String,
    subtitle: String,
    icon: ImageVector,
    iconTint: Color,
    containerColor: Color,
    contentColor: Color,
    subtitleColor: Color,
    border: BorderStroke?,
    enabled: Boolean,
    modifier: Modifier = Modifier,
    onClick: () -> Unit
) {
    Surface(
        onClick = onClick,
        enabled = enabled,
        shape = RoundedCornerShape(18.dp),
        color = containerColor,
        contentColor = contentColor,
        border = border,
        modifier = modifier.heightIn(min = 96.dp)
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(14.dp),
            verticalArrangement = Arrangement.SpaceBetween
        ) {
            Icon(
                imageVector = icon,
                contentDescription = title,
                tint = iconTint,
                modifier = Modifier.size(18.dp)
            )
            Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                Text(
                    text = title,
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.SemiBold,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
                Text(
                    text = subtitle,
                    style = MaterialTheme.typography.bodySmall,
                    color = subtitleColor,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
            }
        }
    }
}
