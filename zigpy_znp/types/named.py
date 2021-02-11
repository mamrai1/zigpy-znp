import sys
import typing
import logging
import dataclasses

from zigpy.types import NWK, EUI64, PanId, KeyData, ClusterId, ExtendedPanId

from . import basic, cstruct

LOGGER = logging.getLogger(__name__)


class ADCChannel(basic.enum_uint8):
    """The ADC channel."""

    AIN0 = 0x00
    AIN1 = 0x01
    AIN2 = 0x02
    AIN3 = 0x03
    AIN4 = 0x04
    AIN5 = 0x05
    AIN6 = 0x06
    AIN7 = 0x07
    Temperature = 0x0E
    Voltage = 0x0F


class ADCResolution(basic.enum_uint8):
    """Resolution of the ADC channel."""

    bits_8 = 0x00
    bits_10 = 0x01
    bits_12 = 0x02
    bits_14 = 0x03


class GpioOperation(basic.enum_uint8):
    """Specifies the type of operation to perform on the GPIO pins."""

    SetDirection = 0x00
    SetInputMode = 0x01
    Set = 0x02
    Clear = 0x03
    Toggle = 0x04
    Read = 0x05


class StackTuneOperation(basic.enum_uint8):
    """The tuning operation to be executed."""

    # XXX: [Value] should correspond to the valid values specified by the
    # ZMacTransmitPower_t enumeration (0xFD - 0x16)
    PowerLevel = 0x00

    # Set RxOnWhenIdle off/on if the value of Value is 0/1;
    # otherwise return the 0x01 current setting of RxOnWhenIdle.
    SetRxOnWhenIdle = 0x01


class AddrMode(basic.enum_uint8):
    """Address mode."""

    NOT_PRESENT = 0x00
    Group = 0x01
    NWK = 0x02
    IEEE = 0x03

    Broadcast = 0x0F


class AddrModeAddress:
    def __new__(cls, mode=None, address=None):
        if mode is not None and address is None and isinstance(mode, cls):
            other = mode
            return cls(mode=other.mode, address=other.address)

        instance = super().__new__(cls)

        if mode is not None and mode == AddrMode.NOT_PRESENT:
            raise ValueError(f"Invalid address mode: {mode}")

        instance.mode = None if mode is None else AddrMode(mode)
        instance.address = (
            None if address is None else instance._get_address_type()(address)
        )

        return instance

    def _get_address_type(self):
        return {
            AddrMode.NWK: NWK,
            AddrMode.Group: NWK,
            AddrMode.Broadcast: NWK,
            AddrMode.IEEE: EUI64,
        }[self.mode]

    @classmethod
    def deserialize(cls, data: bytes) -> "AddrModeAddress":
        mode, data = AddrMode.deserialize(data)
        address, data = EUI64.deserialize(data)

        if mode != AddrMode.IEEE:
            address, _ = NWK.deserialize(address.serialize())

        return cls(mode=mode, address=address), data

    def serialize(self) -> bytes:
        result = (
            self.mode.serialize() + self._get_address_type()(self.address).serialize()
        )

        if self.mode != AddrMode.IEEE:
            result += b"\x00\x00\x00\x00\x00\x00"

        return result

    def __eq__(self, other):
        if not isinstance(self, type(other)) and not isinstance(other, type(self)):
            return False

        return self.mode == other.mode and self.address == other.address

    def __repr__(self) -> str:
        return f"{type(self).__name__}(mode={self.mode!r}, address={self.address!r})"


class Beacon(cstruct.CStruct):
    """Beacon message."""

    Src: NWK
    PanId: PanId
    Channel: basic.uint8_t
    PermitJoining: basic.uint8_t
    RouterCapacity: basic.uint8_t
    DeviceCapacity: basic.uint8_t
    ProtocolVersion: basic.uint8_t
    StackProfile: basic.uint8_t
    LQI: basic.uint8_t
    Depth: basic.uint8_t
    UpdateId: basic.uint8_t
    ExtendedPanId: ExtendedPanId


class GroupId(basic.uint16_t, hex_repr=True):
    """"Group ID class"""

    pass


class ScanType(basic.enum_uint8):
    EnergyDetect = 0x00
    Active = 0x01
    Passive = 0x02
    Orphan = 0x03


@dataclasses.dataclass(frozen=True)
class Param:
    """Schema parameter"""

    name: str
    type: typing.Any = None
    description: str = ""
    optional: bool = False


class MissingEnumMixin:
    @classmethod
    def _missing_(cls, value):
        if not isinstance(value, int):
            raise ValueError(f"{value} is not a valid {cls.__name__}")

        new_member = cls._member_type_.__new__(cls, value)
        new_member._name_ = f"unknown_0x{value:02X}"
        new_member._value_ = cls._member_type_(value)

        if sys.version_info >= (3, 8):
            # Show the warning in the calling code, not in this function
            LOGGER.warning(
                "Unhandled %s value: %s", cls.__name__, new_member, stacklevel=2
            )
        else:
            LOGGER.warning("Unhandled %s value: %s", cls.__name__, new_member)

        return new_member


class Status(MissingEnumMixin, basic.enum_uint8):
    SUCCESS = 0x00
    FAILURE = 0x01
    INVALID_PARAMETER = 0x02
    INVALID_TASK = 0x03
    MSG_BUFFER_NOT_AVAIL = 0x04
    INVALID_MSG_POINTER = 0x05
    INVALID_EVENT_ID = 0x06
    INVALID_INTERRUPT_ID = 0x07
    NO_TIMER_AVAIL = 0x08
    NV_ITEM_UNINIT = 0x09
    NV_OPER_FAILED = 0x0A
    INVALID_MEM_SIZE = 0x0B
    NV_BAD_ITEM_LEN = 0x0C

    MEM_ERROR = 0x10
    BUFFER_FULL = 0x11
    UNSUPPORTED_MODE = 0x12
    MAC_MEM_ERROR = 0x13

    SAPI_IN_PROGRESS = 0x20
    SAPI_TIMEOUT = 0x21
    SAPI_INIT = 0x22

    NOT_AUTHORIZED = 0x7E

    MALFORMED_CMD = 0x80
    UNSUP_CLUSTER_CMD = 0x81

    OTA_ABORT = 0x95
    OTA_IMAGE_INVALID = 0x96
    OTA_WAIT_FOR_DATA = 0x97
    OTA_NO_IMAGE_AVAILABLE = 0x98
    OTA_REQUIRE_MORE_IMAGE = 0x99

    APS_FAIL = 0xB1
    APS_TABLE_FULL = 0xB2
    APS_ILLEGAL_REQUEST = 0xB3
    APS_INVALID_BINDING = 0xB4
    APS_UNSUPPORTED_ATTRIB = 0xB5
    APS_NOT_SUPPORTED = 0xB6
    APS_NO_ACK = 0xB7
    APS_DUPLICATE_ENTRY = 0xB8
    APS_NO_BOUND_DEVICE = 0xB9
    APS_NOT_ALLOWED = 0xBA
    APS_NOT_AUTHENTICATED = 0xBB

    SEC_NO_KEY = 0xA1
    SEC_OLD_FRM_COUNT = 0xA2
    SEC_MAX_FRM_COUNT = 0xA3
    SEC_CCM_FAIL = 0xA4
    SEC_FAILURE = 0xAD

    NWK_INVALID_PARAM = 0xC1
    NWK_INVALID_REQUEST = 0xC2
    NWK_NOT_PERMITTED = 0xC3
    NWK_STARTUP_FAILURE = 0xC4
    NWK_ALREADY_PRESENT = 0xC5
    NWK_SYNC_FAILURE = 0xC6
    NWK_TABLE_FULL = 0xC7
    NWK_UNKNOWN_DEVICE = 0xC8
    NWK_UNSUPPORTED_ATTRIBUTE = 0xC9
    NWK_NO_NETWORKS = 0xCA
    NWK_LEAVE_UNCONFIRMED = 0xCB
    NWK_NO_ACK = 0xCC  # not in spec
    NWK_NO_ROUTE = 0xCD

    # The operation is not supported in the current configuration
    MAC_UNSUPPORTED = 0x18

    # The operation could not be performed in the current state
    MAC_BAD_STATE = 0x19

    # The operation could not be completed because no memory resources were available
    MAC_NO_RESOURCES = 0x1A

    # For internal use only
    MAC_ACK_PENDING = 0x1B

    # For internal use only
    MAC_NO_TIME = 0x1C

    # For internal use only
    MAC_TX_ABORTED = 0x1D

    # For internal use only - A duplicated entry is added to the source matching table
    MAC_DUPLICATED_ENTRY = 0x1E

    # The frame counter puportedly applied by the originator of the received frame
    # is invalid
    MAC_COUNTER_ERROR = 0xDB

    # The key purportedly applied by the originator of the received frame is not allowed
    MAC_IMPROPER_KEY_TYPE = 0xDC

    # The security level purportedly applied by the originator of the received frame
    # does not meet the minimum security level
    MAC_IMPROPER_SECURITY_LEVEL = 0xDD

    # The received frame was secured with legacy security which is not supported
    MAC_UNSUPPORTED_LEGACY = 0xDE

    # The security of the received frame is not supported
    MAC_UNSUPPORTED_SECURITY = 0xDF

    # The beacon was lost following a synchronization request
    MAC_BEACON_LOSS = 0xE0

    # The operation or data request failed because of activity on the channel
    MAC_CHANNEL_ACCESS_FAILURE = 0xE1

    # The MAC was not able to enter low power mode.
    MAC_DENIED = 0xE2

    # Unused
    MAC_DISABLE_TRX_FAILURE = 0xE3

    # Cryptographic processing of the secure frame failed
    MAC_SECURITY_ERROR = 0xE4

    # The received frame or frame resulting from an operation or data request is
    # too long to be processed by the MAC
    MAC_FRAME_TOO_LONG = 0xE5

    # Unused
    MAC_INVALID_GTS = 0xE6

    # The purge request contained an invalid handle
    MAC_INVALID_HANDLE = 0xE7

    # The API function parameter is out of range
    MAC_INVALID_PARAMETER = 0xE8

    # The operation or data request failed because no acknowledgement was received
    MAC_NO_ACK = 0xE9

    # The scan request failed because no beacons were received or the orphan scan failed
    # because no coordinator realignment was received
    MAC_NO_BEACON = 0xEA

    # The associate request failed because no associate response was received or the
    # poll request did not return any data
    MAC_NO_DATA = 0xEB

    # The short address parameter of the start request was invalid
    MAC_NO_SHORT_ADDRESS = 0xEC

    # Unused
    MAC_OUT_OF_CAP = 0xED

    # A PAN identifier conflict has been detected and communicated to the PAN
    # coordinator
    MAC_PAN_ID_CONFLICT = 0xEE

    # A coordinator realignment command has been received
    MAC_REALIGNMENT = 0xEF

    # The associate response, disassociate request, or indirect data transmission failed
    # because the peer device did not respond before the transaction expired or was
    # purged
    MAC_TRANSACTION_EXPIRED = 0xF0

    # The request failed because MAC data buffers are full
    MAC_TRANSACTION_OVERFLOW = 0xF1

    # Unused
    MAC_TX_ACTIVE = 0xF2

    # The operation or data request failed because the security key is not available
    MAC_UNAVAILABLE_KEY = 0xF3

    # The set or get request failed because the attribute is not supported
    MAC_UNSUPPORTED_ATTRIBUTE = 0xF4

    # The data request failed because neither the source address nor destination address
    # parameters were present
    MAC_INVALID_ADDRESS = 0xF5

    # Unused
    MAC_ON_TIME_TOO_LONG = 0xF6

    # Unused
    MAC_PAST_TIME = 0xF7

    # The start request failed because the device is not tracking the beacon of its
    # coordinator
    MAC_TRACKING_OFF = 0xF8

    # Unused
    MAC_INVALID_INDEX = 0xF9

    # The scan terminated because the PAN descriptor storage limit was reached
    MAC_LIMIT_REACHED = 0xFA

    # A set request was issued with a read-only identifier
    MAC_READ_ONLY = 0xFB

    # The scan request failed because a scan is already in progress
    MAC_SCAN_IN_PROGRESS = 0xFC

    # The beacon start time overlapped the coordinator transmission time
    MAC_SUPERFRAME_OVERLAP = 0xFD

    # The AUTOPEND pending all is turned on
    MAC_AUTOACK_PENDING_ALL_ON = 0xFE

    # The AUTOPEND pending all is turned off
    MAC_AUTOACK_PENDING_ALL_OFF = 0xFF


class ResetReason(basic.enum_uint8):
    PowerUp = 0x00
    External = 0x01
    Watchdog = 0x02


class ResetType(basic.enum_uint8):
    Hard = 0x00
    Soft = 0x01
    Shutdown = 0x02


class KeySource(basic.FixedList, item_type=basic.uint8_t, length=8):
    pass


class StartupOptions(basic.enum_flag_uint8):
    ClearConfig = 1 << 0
    ClearState = 1 << 1
    AutoStart = 1 << 2

    # FrameCounter should persist across factory resets.
    # This should not be used as part of FN reset procedure.
    # Set to reset the FrameCounter of all Nwk Security Material
    ClearNwkFrameCounter = 1 << 7


class DeviceLogicalType(basic.enum_uint8):
    Coordinator = 0
    Router = 1
    EndDevice = 2


class DeviceTypeCapabilities(basic.enum_flag_uint8):
    Coordinator = 1 << 0
    Router = 1 << 1
    EndDevice = 1 << 2


class ClusterIdList(basic.LVList, item_type=ClusterId, length_type=basic.uint8_t):
    pass


class NWKList(basic.LVList, item_type=NWK, length_type=basic.uint8_t):
    pass


class TCLinkKey(cstruct.CStruct):
    ExtAddr: EUI64
    Key: KeyData
    TxFrameCounter: basic.uint32_t
    RxFrameCounter: basic.uint32_t


class NwkKeyDesc(cstruct.CStruct):
    KeySeqNum: basic.uint8_t
    Key: KeyData


class NwkActiveKeyItems(cstruct.CStruct):
    Active: NwkKeyDesc
    FrameCounter: basic.uint32_t


class KeyType(MissingEnumMixin, basic.enum_uint8):
    NONE = 0

    # Standard Network Key
    NWK = 1
    # Application Master Key
    APP_MASTER = 2
    # Application Link Key
    APP_LINK = 3
    # Trust Center Link Key
    TC_LINK = 4

    # XXX: just "6" in the Z-Stack source
    UNKNOWN_6 = 6


class KeyAttributes(basic.enum_uint8):
    # Used for IC derived keys
    PROVISIONAL_KEY = 0x00
    # Unique key that is not verified
    UNVERIFIED_KEY = 0x01
    # Unique key that got verified by ZC
    VERIFIED_KEY = 0x02

    # Internal definitions

    # Use default key to join
    DISTRIBUTED_DEFAULT_KEY = 0xFC
    # Joined a network which is not R21 nwk, so TCLK process finished.
    NON_R21_NWK_JOINED = 0xFD
    # Unique key that got verified by Joining device.
    # This means that key is stored as plain text (not seed hashed)
    VERIFIED_KEY_JOINING_DEV = 0xFE
    # Entry using default key
    DEFAULT_KEY = 0xFF


class TCLKDevEntry(cstruct.CStruct):
    txFrmCntr: basic.uint32_t
    rxFrmCntr: basic.uint32_t

    extAddr: EUI64
    keyAttributes: KeyAttributes
    keyType: KeyType

    # For Unique key this is the number of shifts
    # for IC this is the offset on the NvId index
    SeedShift_IcIndex: basic.uint8_t


class NwkSecMaterialDesc(cstruct.CStruct):
    FrameCounter: basic.uint32_t
    ExtendedPanID: EUI64


class AddrMgrUserType(basic.enum_flag_uint8):
    Default = 0x00
    Assoc = 0x01
    Security = 0x02
    Binding = 0x04
    Private1 = 0x08


class AddrMgrEntry(cstruct.CStruct):
    type: AddrMgrUserType
    nwkAddr: NWK
    extAddr: EUI64


EMPTY_ADDR_MGR_ENTRY = AddrMgrEntry(
    type=AddrMgrUserType.Default,
    nwkAddr=0xFFFF,
    extAddr=EUI64.convert("FF:FF:FF:FF:FF:FF:FF:FF"),
)


class AddressManagerTable(basic.CompleteList, item_type=AddrMgrEntry):
    pass


class AuthenticationOption(basic.enum_uint8):
    NotAuthenticated = 0x00
    AuthenticatedCBCK = 0x01
    AuthenticatedEA = 0x02


class LinkKeyTableEntry(cstruct.CStruct):
    Key: KeyData
    TxFrameCounter: basic.uint32_t
    RxFrameCounter: basic.uint32_t


class APSLinkKeyTableEntry(cstruct.CStruct):
    AddressManagerIndex: basic.uint16_t
    LinkKeyTableOffset: basic.uint16_t
    AuthenticationState: AuthenticationOption


class APSLinkKeyTable(
    basic.LVList, length_type=basic.uint16_t, item_type=APSLinkKeyTableEntry
):
    pass
