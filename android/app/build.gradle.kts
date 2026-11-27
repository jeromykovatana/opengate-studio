import java.io.File

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python")
}

val repoRootDir = rootProject.projectDir.parentFile
val venvPython = File(repoRootDir, ".venv/bin/python")
val buildPythonPath = if (venvPython.isFile) venvPython.absolutePath else "python3"

android {
    namespace = "org.opengatestudio.android"
    compileSdk = 35

    defaultConfig {
        applicationId = "org.opengatestudio.android"
        minSdk = 28
        targetSdk = 35
        versionCode = 3
        versionName = "0.3.0-alpha"

        ndk {
            abiFilters += listOf("arm64-v8a", "x86_64")
        }
    }

    buildFeatures {
        compose = true
    }

    composeOptions {
        kotlinCompilerExtensionVersion = "1.5.15"
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }
}

chaquopy {
    defaultConfig {
        version = "3.10"
        buildPython(buildPythonPath)
    }
    sourceSets {
        getByName("main") {
            srcDir("../python")
        }
    }
}

val generateOpenGateKitAssets by tasks.registering(Exec::class) {
    description = "Package clean-room opengate_kit.zip and payload_manifest.json into assets/"
    group = "opengate"
    workingDir = projectDir
    commandLine(
        buildPythonPath,
        "../../scripts/build_android_kit.py",
        "--out-dir",
        "src/main/assets",
    )
}

tasks.named("preBuild") {
    dependsOn(generateOpenGateKitAssets)
}

dependencies {
    implementation(platform("androidx.compose:compose-bom:2024.09.03"))
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.activity:activity-compose:1.9.3")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    testImplementation("junit:junit:4.13.2")
}
