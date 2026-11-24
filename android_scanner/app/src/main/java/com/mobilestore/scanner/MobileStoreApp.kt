package com.mobilestore.scanner

import android.app.Application
import com.mobilestore.scanner.data.ConnectionSettings
import com.mobilestore.scanner.data.ReceivingDraftDatabase
import com.mobilestore.scanner.network.LocalWifiNetworkManager
import com.mobilestore.scanner.network.MobileStoreWsClient
import com.mobilestore.scanner.scanner.FeedbackManager

class MobileStoreApp : Application() {
    lateinit var settings: ConnectionSettings
        private set
    lateinit var draftDb: ReceivingDraftDatabase
        private set
    lateinit var wifiManager: LocalWifiNetworkManager
        private set
    lateinit var wsClient: MobileStoreWsClient
        private set
    lateinit var feedback: FeedbackManager
        private set

    override fun onCreate() {
        super.onCreate()
        settings = ConnectionSettings(this)
        draftDb = ReceivingDraftDatabase.create(this)
        wifiManager = LocalWifiNetworkManager(this)
        wsClient = MobileStoreWsClient(settings, wifiManager)
        feedback = FeedbackManager(this)
    }
}
