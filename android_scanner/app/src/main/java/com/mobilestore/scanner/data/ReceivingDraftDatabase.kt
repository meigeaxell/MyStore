package com.mobilestore.scanner.data

import android.content.Context
import androidx.room.Dao
import androidx.room.Database
import androidx.room.Entity
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.PrimaryKey
import androidx.room.Query
import androidx.room.Room
import androidx.room.RoomDatabase
import kotlinx.coroutines.flow.Flow

@Entity(tableName = "receiving_draft_meta")
data class ReceivingDraftMeta(
    @PrimaryKey val id: Int = 1,
    val requestId: String,
    val productId: Int? = null,
    val productName: String = "",
    val supplierName: String = "",
    val unitCost: String = "",
    val currency: String = "USD",
    val exchangeRate: String = "19.5000",
    val note: String = "",
    val nonImeiQuantity: Int = 1,
    val useImeiMode: Boolean = true,
)

@Entity(tableName = "receiving_draft_imeis")
data class ReceivingDraftImei(
    @PrimaryKey val imei1: String,
    val imei2: String? = null,
    val serialNumber: String? = null,
    val condition: String = "new",
    val luhnValid: Boolean = true,
    val serverVerified: Boolean = false,
    val addedAt: Long = System.currentTimeMillis(),
)

@Dao
interface ReceivingDraftDao {
    @Query("SELECT * FROM receiving_draft_meta WHERE id = 1")
    fun observeMeta(): Flow<ReceivingDraftMeta?>

    @Query("SELECT * FROM receiving_draft_meta WHERE id = 1")
    suspend fun getMeta(): ReceivingDraftMeta?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsertMeta(meta: ReceivingDraftMeta)

    @Query("DELETE FROM receiving_draft_meta")
    suspend fun clearMeta()

    @Query("SELECT * FROM receiving_draft_imeis ORDER BY addedAt DESC")
    fun observeImeis(): Flow<List<ReceivingDraftImei>>

    @Query("SELECT * FROM receiving_draft_imeis ORDER BY addedAt ASC")
    suspend fun getImeis(): List<ReceivingDraftImei>

    @Insert(onConflict = OnConflictStrategy.IGNORE)
    suspend fun insertImei(entry: ReceivingDraftImei): Long

    @Query("DELETE FROM receiving_draft_imeis WHERE imei1 = :imei1")
    suspend fun deleteImei(imei1: String)

    @Query("DELETE FROM receiving_draft_imeis")
    suspend fun clearImeis()
}

@Database(
    entities = [ReceivingDraftMeta::class, ReceivingDraftImei::class],
    version = 1,
    exportSchema = false,
)
abstract class ReceivingDraftDatabase : RoomDatabase() {
    abstract fun draftDao(): ReceivingDraftDao

    companion object {
        fun create(context: Context): ReceivingDraftDatabase =
            Room.databaseBuilder(
                context.applicationContext,
                ReceivingDraftDatabase::class.java,
                "mobilestore_receiving_drafts.db",
            ).build()
    }
}
