import typing
import logging
import dataclasses

import zigpy_znp.types as t
from zigpy_znp.exceptions import SecurityError
from zigpy_znp.types.nvids import ExNvIds, OsalNvIds
from zigpy_znp.zigbee.application import ControllerApplication

LOGGER = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class StoredDevice:
    ieee: t.EUI64
    nwk: t.NWK

    hashed_link_key_shift: t.uint8_t = None
    aps_link_key: t.KeyData = None

    tx_counter: t.uint32_t = None
    rx_counter: t.uint32_t = None

    def replace(self, **kwargs):
        return dataclasses.replace(self, **kwargs)


def rotate(lst, n):
    return lst[n:] + lst[:n]


def compute_key(ieee, seed, shift):
    rotated_seed = rotate(seed, n=shift)
    return t.KeyData([a ^ b for a, b in zip(rotated_seed, 2 * ieee.serialize())])


def compute_seed(ieee, key, shift):
    rotated_seed = bytes(a ^ b for a, b in zip(key, 2 * ieee.serialize()))
    return rotate(rotated_seed, n=-shift)


def find_key_shift(ieee, key, seed):
    for shift in range(0x00, 0x0F + 1):
        if seed == compute_seed(ieee, key, shift):
            return shift

    return None


def iter_seed_candidates(ieees_and_keys):
    for ieee, key in ieees_and_keys:
        # Derive a seed from each candidate
        seed = compute_seed(ieee, key, 0)

        # And see how many other keys share this same seed
        count = sum(find_key_shift(i, k, seed) is not None for i, k in ieees_and_keys)

        yield count, seed

        # If all of the keys are derived from this seed, we can stop searching
        if count == len(ieees_and_keys):
            break


async def read_tc_frame_counter(app: ControllerApplication) -> t.uint32_t:
    if app._znp.version == 1.2:
        key_info = await app._znp.nvram.osal_read(
            OsalNvIds.NWKKEY, item_type=t.NwkActiveKeyItems
        )

        return key_info.FrameCounter

    global_entry = None

    if app._znp.version == 3.0:
        entries = app._znp.nvram.osal_read_table(
            OsalNvIds.LEGACY_NWK_SEC_MATERIAL_TABLE_START,
            OsalNvIds.LEGACY_NWK_SEC_MATERIAL_TABLE_END,
            item_type=t.NwkSecMaterialDesc,
        )
    else:
        entries = app._znp.nvram.read_table(
            item_id=ExNvIds.NWK_SEC_MATERIAL_TABLE,
            item_type=t.NwkSecMaterialDesc,
        )

    async for entry in entries:
        if entry.ExtendedPanID == app.extended_pan_id:
            # Always prefer the entry for our current network
            return entry.FrameCounter
        elif entry.ExtendedPanID == t.EUI64.convert("FF:FF:FF:FF:FF:FF:FF:FF"):
            # But keep track of the global entry if it already exists
            global_entry = entry

    if global_entry is None:
        raise RuntimeError("No security material entry was found for this network")

    return global_entry.FrameCounter


async def write_tc_frame_counter(app: ControllerApplication, counter: t.uint32_t):
    if app._znp.version == 1.2:
        key_info = await app._znp.nvram.osal_read(
            OsalNvIds.NWKKEY, item_type=t.NwkActiveKeyItems
        )
        key_info.FrameCounter = counter

        await app._znp.nvram.osal_write(OsalNvIds.NWKKEY, key_info)

        return

    best_entry = None
    best_address = None

    if app._znp.version == 3.0:
        address = OsalNvIds.LEGACY_NWK_SEC_MATERIAL_TABLE_START
        entries = app._znp.nvram.osal_read_table(
            start_nvid=OsalNvIds.LEGACY_NWK_SEC_MATERIAL_TABLE_START,
            end_nvid=OsalNvIds.LEGACY_NWK_SEC_MATERIAL_TABLE_END,
            item_type=t.NwkSecMaterialDesc,
        )
    else:
        address = 0x0000
        entries = app._znp.nvram.read_table(
            item_id=ExNvIds.NWK_SEC_MATERIAL_TABLE,
            item_type=t.NwkSecMaterialDesc,
        )

    async for entry in entries:
        if entry.ExtendedPanID == app.extended_pan_id:
            best_entry = entry
            best_address = address
            break
        elif best_entry is None and entry.ExtendedPanID == t.EUI64.convert(
            "FF:FF:FF:FF:FF:FF:FF:FF"
        ):
            best_entry = entry
            best_address = address

        address += 0x0001
    else:
        raise RuntimeError("Failed to find open slot for security material entry")

    best_entry.FrameCounter = counter

    if app._znp.version == 3.0:
        await app._znp.nvram.osal_write(best_address, best_entry)
    else:
        await app._znp.nvram.write(
            item_id=ExNvIds.NWK_SEC_MATERIAL_TABLE,
            sub_id=best_address,
            value=best_entry,
        )


async def read_addr_mgr_entries(app: ControllerApplication):
    if app._znp.version >= 3.30:
        entries = [
            entry
            async for entry in app._znp.nvram.read_table(
                item_id=ExNvIds.ADDRMGR,
                item_type=t.AddrMgrEntry,
            )
        ]
    else:
        entries = list(
            await app._znp.nvram.osal_read(
                OsalNvIds.ADDRMGR, item_type=t.AddressManagerTable
            )
        )

    return entries


async def read_hashed_link_keys(app, tclk_seed):
    if tclk_seed is None:
        return

    if app._znp.version == 3.30:
        entries = app._znp.nvram.read_table(
            item_id=ExNvIds.TCLK_TABLE,
            item_type=t.TCLKDevEntry,
        )
    else:
        entries = app._znp.nvram.osal_read_table(
            start_nvid=OsalNvIds.LEGACY_TCLK_TABLE_START,
            end_nvid=OsalNvIds.LEGACY_TCLK_TABLE_END,
            item_type=t.TCLKDevEntry,
        )

    async for entry in entries:
        if entry.extAddr == t.EUI64.convert("00:00:00:00:00:00:00:00"):
            continue

        # XXX: why do both of these types appear?
        # assert entry.keyType == t.KeyType.NWK
        # assert entry.keyType == t.KeyType.NONE

        ieee = entry.extAddr.serialize()
        rotated_seed = rotate(tclk_seed, n=entry.SeedShift_IcIndex)
        link_key_data = bytes(a ^ b for a, b in zip(rotated_seed, ieee + ieee))
        link_key, _ = t.KeyData.deserialize(link_key_data)

        yield entry.extAddr, entry.txFrmCntr, entry.rxFrmCntr, link_key


async def read_unhashed_link_keys(app, addr_mgr_entries):
    if app._znp.version == 3.30:
        link_key_offset_base = 0x0000
        table = app._znp.nvram.read_table(
            item_id=ExNvIds.APS_KEY_DATA_TABLE,
            item_type=t.APSKeyDataTableEntry,
        )
    else:
        link_key_offset_base = OsalNvIds.LEGACY_APS_LINK_KEY_DATA_START
        table = app._znp.nvram.osal_read_table(
            start_nvid=OsalNvIds.LEGACY_APS_LINK_KEY_DATA_START,
            end_nvid=OsalNvIds.LEGACY_APS_LINK_KEY_DATA_END,
            item_type=t.APSKeyDataTableEntry,
        )

    try:
        aps_key_data_table = [entry async for entry in table]
    except SecurityError:
        # CC2531 with Z-Stack Home 1.2 just doesn't let you read this data out
        return

    link_key_table, _ = t.APSLinkKeyTable.deserialize(
        await app._znp.nvram.osal_read(OsalNvIds.APS_LINK_KEY_TABLE)
    )

    for entry in link_key_table:
        if not entry.AuthenticationState & t.AuthenticationOption.AuthenticatedCBCK:
            continue

        key_table_entry = aps_key_data_table[entry.LinkKeyNvId - link_key_offset_base]
        addr_mgr_entry = addr_mgr_entries[entry.AddressManagerIndex]

        assert addr_mgr_entry.type & t.AddrMgrUserType.Assoc
        assert addr_mgr_entry.type & t.AddrMgrUserType.Security

        yield (
            addr_mgr_entry.extAddr,
            key_table_entry.TxFrameCounter,
            key_table_entry.RxFrameCounter,
            key_table_entry.Key,
        )


async def read_devices(app: ControllerApplication):
    tclk_seed = None

    if app._znp.version > 1.2:
        tclk_seed = await app._znp.nvram.osal_read(
            OsalNvIds.TCLK_SEED, item_type=t.KeyData
        )

    addr_mgr = await read_addr_mgr_entries(app)
    devices = {}

    for entry in addr_mgr:
        if entry.nwkAddr == 0xFFFF:
            continue
        elif entry.type in (
            t.AddrMgrUserType.Assoc,
            t.AddrMgrUserType.Assoc | t.AddrMgrUserType.Security,
        ):
            devices[entry.extAddr] = StoredDevice(
                ieee=entry.extAddr,
                nwk=entry.nwkAddr,
            )
        else:
            raise ValueError(f"Unexpected entry type: {entry.type}")

    async for ieee, tx_ctr, rx_ctr, key in read_hashed_link_keys(app, tclk_seed):
        devices[ieee] = devices[ieee].replace(
            tx_counter=tx_ctr,
            rx_counter=rx_ctr,
            aps_link_key=key,
            hashed_link_key_shift=find_key_shift(ieee, key, tclk_seed),
        )

    async for ieee, tx_ctr, rx_ctr, key in read_unhashed_link_keys(app, addr_mgr):
        devices[ieee] = devices[ieee].replace(
            tx_counter=tx_ctr,
            rx_counter=rx_ctr,
            aps_link_key=key,
        )

    return list(devices.values())


async def write_addr_manager_entries(app: ControllerApplication, devices):
    entries = [
        t.AddrMgrEntry(
            type=t.AddrMgrUserType.Security | t.AddrMgrUserType.Assoc
            if d.aps_link_key
            else t.AddrMgrUserType.Assoc,
            nwkAddr=d.nwk,
            extAddr=d.ieee,
        )
        for d in devices
    ]

    if app._znp.version >= 3.30:
        await app._znp.nvram.write_table(
            item_id=ExNvIds.ADDRMGR,
            values=entries,
            fill_value=t.EMPTY_ADDR_MGR_ENTRY,
        )
        return

    # On older devices this "table" is a single array in NVRAM whose size is dependent
    # on compile-time constants
    old_entries = await app._znp.nvram.osal_read(
        OsalNvIds.ADDRMGR, item_type=t.AddressManagerTable
    )
    new_entries = len(old_entries) * [t.EMPTY_ADDR_MGR_ENTRY]

    for index, entry in enumerate(entries):
        new_entries[index] = entry

    await app._znp.nvram.osal_write(
        OsalNvIds.ADDRMGR, t.AddressManagerTable(new_entries)
    )


async def write_devices(
    app: ControllerApplication,
    devices: typing.Iterable[typing.Dict],
    counter_increment: t.uint32_t = 2500,
    seed=None,
):
    # Make sure we prioritize the devices with keys if there is no room
    # devices = sorted(devices, key=lambda e: e.get("link_key") is None)

    ieees_and_keys = [(d.ieee, d.aps_link_key) for d in devices if d.aps_link_key]

    # Find the seed that maximizes the number of keys that can be derived from it
    if seed is None and ieees_and_keys:
        _, seed = max(iter_seed_candidates(ieees_and_keys))

    hashed_link_key_table = []
    aps_key_data_table = []
    link_key_table = t.APSLinkKeyTable()

    for index, device in enumerate(devices):
        if not device.aps_link_key:
            continue

        shift = find_key_shift(device.ieee, device.aps_link_key, seed)

        if shift is not None:
            # Hashed link keys can be written into the TCLK table
            hashed_link_key_table.append(
                t.TCLKDevEntry(
                    txFrmCntr=device.tx_counter + counter_increment,
                    rxFrmCntr=device.rx_counter,
                    extAddr=device.ieee,
                    keyAttributes=t.KeyAttributes.DEFAULT_KEY,
                    keyType=t.KeyType.NWK,
                    SeedShift_IcIndex=shift,
                )
            )
        else:
            # Unhashed link keys are written to a table
            aps_key_data_table.append(
                t.APSKeyDataTableEntry(
                    Key=device.aps_link_key,
                    TxFrameCounter=device.tx_counter + counter_increment,
                    RxFrameCounter=device.rx_counter,
                )
            )

            if app._znp.version > 3.0:
                start = 0x0000
            else:
                start = OsalNvIds.LEGACY_APS_LINK_KEY_DATA_START

            offset = len(aps_key_data_table) - 1

            # And their position within the above table is stored in this table
            link_key_table.append(
                t.APSLinkKeyTableEntry(
                    AddressManagerIndex=index,
                    LinkKeyNvId=start + offset,
                    AuthenticationState=t.AuthenticationOption.AuthenticatedCBCK,
                )
            )

    old_link_key_table = await app._znp.nvram.osal_read(OsalNvIds.APS_LINK_KEY_TABLE)
    link_key_table_value = link_key_table.serialize().ljust(
        len(old_link_key_table), b"\x00"
    )

    if len(link_key_table.serialize()) > len(old_link_key_table):
        raise RuntimeError("New link key table is larger than the current one")

    # Postpone writes until all of the table entries have been created
    await write_addr_manager_entries(app, devices)
    await app._znp.nvram.osal_write(OsalNvIds.APS_LINK_KEY_TABLE, link_key_table_value)

    tclk_fill_value = t.TCLKDevEntry(
        txFrmCntr=0,
        rxFrmCntr=0,
        extAddr=t.EUI64.convert("00:00:00:00:00:00:00:00"),
        keyAttributes=t.KeyAttributes.PROVISIONAL_KEY,
        keyType=t.KeyType.NONE,
        SeedShift_IcIndex=0,
    )

    if app._znp.version > 3.0:
        await app._znp.nvram.write_table(
            item_id=ExNvIds.TCLK_TABLE,
            values=hashed_link_key_table,
            fill_value=tclk_fill_value,
        )

        await app._znp.nvram.write_table(
            item_id=ExNvIds.APS_KEY_DATA_TABLE,
            values=aps_key_data_table,
            fill_value=t.APSKeyDataTableEntry(
                Key=t.KeyData([0x00] * 16),
                TxFrameCounter=0,
                RxFrameCounter=0,
            ),
        )
    else:
        await app._znp.nvram.osal_write_table(
            start_nvid=OsalNvIds.LEGACY_TCLK_TABLE_START,
            end_nvid=OsalNvIds.LEGACY_TCLK_TABLE_END,
            values=hashed_link_key_table,
            fill_value=tclk_fill_value,
        )

        await app._znp.nvram.osal_write_table(
            start_nvid=OsalNvIds.LEGACY_APS_LINK_KEY_DATA_START,
            end_nvid=OsalNvIds.LEGACY_APS_LINK_KEY_DATA_END,
            values=aps_key_data_table,
            fill_value=t.APSKeyDataTableEntry(
                Key=t.KeyData([0x00] * 16),
                TxFrameCounter=0,
                RxFrameCounter=0,
            ),
        )
