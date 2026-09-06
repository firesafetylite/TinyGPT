/* Global boot preference: readable before mounting a system partition. A bad or
 * interrupted record falls back to the safe two-second recovery-key window. */
#define BOOT_TIMER_DEFAULT 2U
#define BOOT_TIMER_MAX 60U
#define BOOT_SETTINGS_MAGIC 0x31544254U
static const CHAR16 gBootSettingsPath[] = {'\\','T','I','N','Y','B','O','O','T','.','D','A','T',0};
typedef struct {
    UINT32 magic, version, seconds, checksum;
} BOOT_SETTINGS_RECORD;

static int boot_settings_read(BOOT_SETTINGS_RECORD *record) {
    EFI_FILE_PROTOCOL *file = (EFI_FILE_PROTOCOL *)0;
    UINT8 data[sizeof(*record) + 1U];
    UINTN bytes = sizeof(data);
    if (!gBootVolumeRoot || gBootVolumeRoot->Open(gBootVolumeRoot, &file,
            (CHAR16 *)gBootSettingsPath, EFI_FILE_MODE_READ, 0) != EFI_SUCCESS || !file) return 0;
    EFI_STATUS status = file->Read(file, &bytes, data);
    EFI_STATUS closed = file->Close(file);
    if (status != EFI_SUCCESS || closed != EFI_SUCCESS || bytes != sizeof(*record)) return 0;
    memory_copy(record, data, sizeof(*record));
    UINT32 checksum = record->checksum;
    record->checksum = 0;
    return record->magic == BOOT_SETTINGS_MAGIC && record->version == 1U &&
        record->seconds >= 1U && record->seconds <= BOOT_TIMER_MAX &&
        checksum == hash_bytes(record, sizeof(*record));
}

static UINT32 boot_settings_seconds(void) {
    BOOT_SETTINGS_RECORD record;
    return boot_settings_read(&record) ? record.seconds : BOOT_TIMER_DEFAULT;
}

/* Call only after administrator authorization: this writes recovery storage. */
static int boot_settings_save(UINT32 seconds) {
    EFI_FILE_PROTOCOL *file = (EFI_FILE_PROTOCOL *)0;
    BOOT_SETTINGS_RECORD record = {BOOT_SETTINGS_MAGIC, 1U, seconds, 0};
    BOOT_SETTINGS_RECORD verified;
    UINTN bytes = sizeof(record);
    if (!gBootVolumeRoot || seconds < 1U || seconds > BOOT_TIMER_MAX) return 0;
    record.checksum = hash_bytes(&record, sizeof(record));
    if (gBootVolumeRoot->Open(gBootVolumeRoot, &file, (CHAR16 *)gBootSettingsPath,
            EFI_FILE_MODE_READ | EFI_FILE_MODE_WRITE | EFI_FILE_MODE_CREATE, 0) != EFI_SUCCESS || !file) return 0;
    EFI_STATUS status = file->SetPosition(file, 0);
    if (status == EFI_SUCCESS) status = file->Write(file, &bytes, &record);
    if (status == EFI_SUCCESS && bytes == sizeof(record)) {
        UINT64 buffer[96];
        UINTN length = sizeof(buffer);
        status = file->GetInfo(file, &gFileInfoGuid, &length, buffer);
        if (status == EFI_SUCCESS) {
            EFI_FILE_INFO *info = (EFI_FILE_INFO *)buffer;
            if (length < 82U || info->Size < 82U || info->Size > length) status = EFI_DEVICE_ERROR;
            else {
                info->FileSize = sizeof(record);
                status = file->SetInfo(file, &gFileInfoGuid, info->Size, info);
            }
        }
        if (status == EFI_SUCCESS) status = file->Flush(file);
    }
    EFI_STATUS closed = file->Close(file);
    return status == EFI_SUCCESS && closed == EFI_SUCCESS && bytes == sizeof(record) &&
        boot_settings_read(&verified) && verified.seconds == seconds;
}
