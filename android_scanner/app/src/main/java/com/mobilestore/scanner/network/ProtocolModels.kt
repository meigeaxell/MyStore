package com.mobilestore.scanner.network

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject

const val PROTOCOL_VERSION = 1

@Serializable
data class WsRequestEnvelope(
    @SerialName("protocol_version") val protocolVersion: Int = PROTOCOL_VERSION,
    val type: String,
    @SerialName("request_id") val requestId: String,
    @SerialName("device_id") val deviceId: String,
    val timestamp: String,
    val payload: JsonObject,
)

@Serializable
data class WsError(
    val code: String = "UNKNOWN",
    val message: String = "Näbelli ýalňyşlyk",
)

@Serializable
data class WsResponseEnvelope(
    @SerialName("protocol_version") val protocolVersion: Int = PROTOCOL_VERSION,
    val type: String = "",
    @SerialName("request_id") val requestId: String = "",
    val ok: Boolean = false,
    val data: JsonElement? = null,
    val error: WsError? = null,
)

@Serializable
data class AuthOkData(
    @SerialName("store_name") val storeName: String = "MobileStore",
    @SerialName("default_currency") val defaultCurrency: String = "TMT",
    @SerialName("default_exchange_rate") val defaultExchangeRate: String = "19.5000",
    @SerialName("server_version") val serverVersion: String = "0.1.0",
    @SerialName("connected_devices_count") val connectedDevicesCount: Int = 1,
)

@Serializable
data class ProductCardData(
    @SerialName("product_id") val productId: Int,
    @SerialName("stock_item_id") val stockItemId: Int? = null,
    val sku: String = "",
    val name: String = "",
    val brand: String = "",
    val model: String = "",
    val specification: String = "",
    @SerialName("category_id") val categoryId: Int? = null,
    @SerialName("category_name") val categoryName: String = "",
    val imei: String? = null,
    val imei2: String? = null,
    @SerialName("serial_number") val serialNumber: String? = null,
    val condition: String = "new",
    @SerialName("stock_quantity") val stockQuantity: Int = 0,
    @SerialName("unit_cost") val unitCost: String = "0.00",
    @SerialName("cost_currency") val costCurrency: String = "TMT",
    @SerialName("last_sale_price") val lastSalePrice: String? = null,
    @SerialName("last_sale_currency") val lastSaleCurrency: String? = null,
    @SerialName("default_currency") val defaultCurrency: String = "TMT",
    @SerialName("exchange_rate") val exchangeRate: String = "19.5000",
    @SerialName("photo_url") val photoUrl: String? = null,
    @SerialName("availability_status") val availabilityStatus: String = "available",
    @SerialName("availability_message") val availabilityMessage: String = "",
    @SerialName("match_type") val matchType: String = "exact",
    @SerialName("match_score") val matchScore: Int = 100,
    @SerialName("match_detail") val matchDetail: String = "",
    @SerialName("scanned_code") val scannedCode: String? = null,
    @SerialName("matched_code") val matchedCode: String? = null,
    @SerialName("requires_confirmation") val requiresConfirmation: Boolean = false,
)

@Serializable
data class ScanMultipleData(
    val code: String = "",
    val items: List<ProductCardData> = emptyList(),
)

@Serializable
data class ImeiCheckResultData(
    val imei1: String = "",
    @SerialName("luhn_valid") val luhnValid: Boolean = false,
    @SerialName("exists_in_db") val existsInDb: Boolean = false,
    @SerialName("can_receive") val canReceive: Boolean = false,
    @SerialName("existing_product") val existingProduct: String? = null,
    @SerialName("existing_status") val existingStatus: String? = null,
    val message: String = "",
)

@Serializable
data class CatalogProductItem(
    val id: Int,
    val sku: String = "",
    val name: String = "",
    @SerialName("category_id") val categoryId: Int? = null,
    val category: String = "",
    val brand: String = "",
    val model: String = "",
    val specification: String = "",
    @SerialName("stock_quantity") val stockQuantity: Int = 0,
    @SerialName("min_stock_quantity") val minStockQuantity: Int = 0,
    @SerialName("new_devices") val newDevices: Int = 0,
    @SerialName("used_devices") val usedDevices: Int = 0,
)

@Serializable
data class CatalogListData(
    val products: List<CatalogProductItem> = emptyList(),
    val total: Int = 0,
)

@Serializable
data class ProductDetailInfo(
    val id: Int,
    val sku: String = "",
    val name: String = "",
    @SerialName("category_id") val categoryId: Int? = null,
    val brand: String = "",
    val model: String = "",
    val specification: String = "",
    @SerialName("stock_quantity") val stockQuantity: Int = 0,
    @SerialName("min_stock_quantity") val minStockQuantity: Int = 0,
    @SerialName("default_cost") val defaultCost: String = "0.00",
    @SerialName("default_cost_currency") val defaultCostCurrency: String = "USD",
)

@Serializable
data class StockDeviceInfo(
    val id: Int,
    val imei1: String = "",
    val imei2: String? = null,
    @SerialName("serial_number") val serialNumber: String? = null,
    val condition: String = "new",
    val status: String = "in_stock",
    @SerialName("unit_cost") val unitCost: String = "0.00",
    @SerialName("cost_currency") val costCurrency: String = "USD",
    val notes: String = "",
)

@Serializable
data class ProductDetailsData(
    val product: ProductDetailInfo,
    val devices: List<StockDeviceInfo> = emptyList(),
)

@Serializable
data class CategoryItem(
    val id: Int,
    val name: String = "",
    val code: String? = null,
    @SerialName("is_active") val isActive: Boolean = true,
    @SerialName("product_count") val productCount: Int = 0,
)

@Serializable
data class CategoryListData(
    val categories: List<CategoryItem> = emptyList(),
)

@Serializable
data class AccessoryOcrParsed(
    @SerialName("normalized_text") val normalizedText: String = "",
    @SerialName("cleaned_query") val cleanedQuery: String = "",
    val brand: String = "",
    val model: String = "",
    @SerialName("accessory_type") val accessoryType: String = "",
    @SerialName("accessory_type_label") val accessoryTypeLabel: String = "",
    val features: List<String> = emptyList(),
)

@Serializable
data class AccessoryDraftSuggestion(
    val name: String = "",
    @SerialName("category_id") val categoryId: Int? = null,
    val brand: String = "",
    val model: String = "",
    val specification: String = "",
    @SerialName("accessory_type") val accessoryType: String = "",
    @SerialName("accessory_type_label") val accessoryTypeLabel: String = "",
)

@Serializable
data class AccessoryOcrCategoryRef(
    val id: Int,
    val name: String = "",
)

@Serializable
data class AccessoryOcrMatchResponse(
    @SerialName("raw_text") val rawText: String = "",
    val parsed: AccessoryOcrParsed = AccessoryOcrParsed(),
    @SerialName("draft_suggestion") val draftSuggestion: AccessoryDraftSuggestion = AccessoryDraftSuggestion(),
    val items: List<ProductCardData> = emptyList(),
    val categories: List<AccessoryOcrCategoryRef> = emptyList(),
)
