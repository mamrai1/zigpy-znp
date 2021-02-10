import json

import pytest

import zigpy_znp.types as t
import zigpy_znp.commands as c
from zigpy_znp.types.nvids import NWK_NVID_TABLES, ExNvIds, OsalNvIds
from zigpy_znp.tools.nvram_read import main as nvram_read
from zigpy_znp.tools.nvram_reset import main as nvram_reset
from zigpy_znp.tools.nvram_write import main as nvram_write

from ..conftest import ALL_DEVICES, BaseZStack1CC2531

pytestmark = [pytest.mark.asyncio]


def not_recognized(req):
    return c.RPCError.CommandNotRecognized.Rsp(
        ErrorCode=c.rpc_error.ErrorCode.InvalidCommandId, RequestHeader=req.header
    )


def dump_nvram(znp):
    obj = {}

    for item_id, items in znp.nvram.items():
        item_id = ExNvIds(item_id)
        item = obj[item_id.name] = {}

        for sub_id, value in items.items():
            # Unnamed pass right through
            if item_id != ExNvIds.LEGACY:
                item[f"0x{sub_id:04X}"] = value.hex()
                continue

            try:
                # Table entries are named differently
                start, end = next(
                    ((s, e) for s, e in NWK_NVID_TABLES.items() if s <= sub_id <= e)
                )
                item[f"{start.name}+{sub_id - start}"] = value.hex()
            except StopIteration:
                item[OsalNvIds(sub_id).name] = value.hex()

    if znp.nib is not None:
        obj["LEGACY"]["NIB"] = znp.nvram_serialize(znp.nib).hex()

    return obj


@pytest.mark.parametrize("device", ALL_DEVICES)
async def test_nvram_read(device, make_znp_server, tmp_path, mocker):
    znp_server = make_znp_server(server_cls=device)

    # Make one reaaally long, requiring multiple writes to read it
    znp_server.nvram[ExNvIds.LEGACY][OsalNvIds.HAS_CONFIGURED_ZSTACK3] = b"\xFF" * 300

    # Make a few secure but unreadable
    if issubclass(device, BaseZStack1CC2531):
        # Normal NVID
        znp_server.nvram[ExNvIds.LEGACY][OsalNvIds.TCLK_SEED] = b"\xFF" * 32

        # Part of a table
        znp_server.nvram[ExNvIds.LEGACY][OsalNvIds.LEGACY_TCLK_TABLE_START] = b"\xFF"

    # XXX: this is not a great way to do it but deepcopy won't work here
    old_nvram_repr = repr(znp_server.nvram)

    backup_file = tmp_path / "backup.json"
    await nvram_read([znp_server._port_path, "-o", str(backup_file), "-vvv"])

    # No NVRAM was modified during the read
    assert repr(znp_server.nvram) == old_nvram_repr

    # Remove the item since it won't be present in the backup
    if issubclass(device, BaseZStack1CC2531):
        del znp_server.nvram[ExNvIds.LEGACY][OsalNvIds.TCLK_SEED]
        del znp_server.nvram[ExNvIds.LEGACY][OsalNvIds.LEGACY_TCLK_TABLE_START]

    # The backup JSON written to disk should be an exact copy
    assert json.loads(backup_file.read_text()) == dump_nvram(znp_server)

    znp_server.close()


@pytest.mark.parametrize("device", ALL_DEVICES)
async def test_nvram_write(device, make_znp_server, tmp_path, mocker):
    znp_server = make_znp_server(server_cls=device)

    # Create a dummy backup
    backup = dump_nvram(znp_server)

    # Change some values
    backup["LEGACY"]["HAS_CONFIGURED_ZSTACK1"] = "ff"

    # Make one with a long value
    backup["LEGACY"]["HAS_CONFIGURED_ZSTACK3"] = "ffee" * 400

    backup_file = tmp_path / "backup.json"
    backup_file.write_text(json.dumps(backup))

    # And clear out all of our NVRAM
    znp_server.nvram = {ExNvIds.LEGACY: {}}

    # This has a differing length
    znp_server.nvram[ExNvIds.LEGACY][OsalNvIds.HAS_CONFIGURED_ZSTACK1] = b"\xEE\xEE"

    # This already exists
    znp_server.nvram[ExNvIds.LEGACY][OsalNvIds.HAS_CONFIGURED_ZSTACK3] = b"\xBB"

    await nvram_write([znp_server._port_path, "-i", str(backup_file)])

    nvram_obj = dump_nvram(znp_server)

    # XXX: should we check that the NVRAMs are *identical*, or that every item in the
    #      backup was completely restored?
    for item_id, sub_ids in backup.items():
        for sub_id, value in sub_ids.items():
            # The NIB is handled differently within tests
            if sub_id == "NIB":
                continue

            assert nvram_obj[item_id][sub_id] == value

    znp_server.close()


@pytest.mark.parametrize("device", ALL_DEVICES)
async def test_nvram_reset_normal(device, make_znp_server, mocker):
    znp_server = make_znp_server(server_cls=device)

    # So we know when it has been changed
    znp_server.nvram[ExNvIds.LEGACY][OsalNvIds.STARTUP_OPTION] = b"\xFF"
    znp_server.nvram[ExNvIds.LEGACY][0xFFFF] = b"test"

    await nvram_reset([znp_server._port_path])

    # We've instructed Z-Stack to reset on next boot
    assert (
        znp_server.nvram[ExNvIds.LEGACY][OsalNvIds.STARTUP_OPTION]
        == (t.StartupOptions.ClearConfig | t.StartupOptions.ClearState).serialize()
    )

    # And none of the "CONFIGURED" values exist
    assert OsalNvIds.HAS_CONFIGURED_ZSTACK1 not in znp_server.nvram[ExNvIds.LEGACY]
    assert OsalNvIds.HAS_CONFIGURED_ZSTACK3 not in znp_server.nvram[ExNvIds.LEGACY]

    # But our custom value has not been touched
    assert znp_server.nvram[ExNvIds.LEGACY][0xFFFF] == b"test"

    znp_server.close()


@pytest.mark.parametrize("device", ALL_DEVICES)
async def test_nvram_reset_everything(device, make_znp_server, mocker):
    znp_server = make_znp_server(server_cls=device)
    znp_server.nvram[ExNvIds.LEGACY][OsalNvIds.STARTUP_OPTION] = b"\xFF"

    await nvram_reset(["-c", znp_server._port_path])

    # Nothing exists but the synthetic POLL_RATE_OLD16 and STARTUP_OPTION
    assert len(znp_server.nvram[ExNvIds.LEGACY].keys()) == 2
    assert len([v for v in znp_server.nvram.values() if v]) == 1
    assert OsalNvIds.POLL_RATE_OLD16 in znp_server.nvram[ExNvIds.LEGACY]
    assert (
        znp_server.nvram[ExNvIds.LEGACY][OsalNvIds.STARTUP_OPTION]
        == (t.StartupOptions.ClearConfig | t.StartupOptions.ClearState).serialize()
    )

    znp_server.close()
