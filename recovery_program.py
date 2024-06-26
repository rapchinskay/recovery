import pytsk3
import binascii
import struct
import datetime
import argparse

parser = argparse.ArgumentParser(description="NTFS image analyzer")
parser.add_argument("image_path", help="Path to NTFS image file")
args = parser.parse_args()
# numbers of clusters with contents
def p_runlist(runlist_data):
    runlist = []
    offset = 0
    current_cluster = 0
    while True:
        header = runlist_data[offset]
        if header == 0:
            break
        size = header & 0xF
        offset_size = header >> 4
        run_length = struct.unpack('<Q', runlist_data[offset+1:offset+1+size] + b'\x00'*(8-size))[0]
        run_offset = struct.unpack('<q', runlist_data[offset+1+size:offset+1+size+offset_size] + b'\x00'*(8-offset_size))[0]
        current_cluster += run_offset
        runlist.append((current_cluster, current_cluster + run_length))
        offset += 1 +size +offset_size
    return runlist
# cluster size calculation
def size_cluster(image_path):
    with open(image_path, 'rb') as f:
        f.seek(0x0B)
        bytes_per_sector = int.from_bytes(f.read(2), byteorder='little')
        f.seek(0x0D)
        sectors_per_cluster = int.from_bytes(f.read(1), byteorder='little')
        return bytes_per_sector * sectors_per_cluster
    
# cluster content search
def read_cluster(image_path, cluster_number, cluster_size):
    with open(image_path, 'rb') as f:
        f.seek(cluster_number * cluster_size)
        return f.read(cluster_size)

# time format conversion 
def filetime_to_dt(ft): 
    us = (ft - 116444736000000000) // 10
    return (datetime.datetime(1970, 1, 1) +
            datetime.timedelta(microseconds=us)).strftime("%Y-%m-%d %H:%M:%S")
# processing attribute $STANDARD_INFORMATION
def standard_information(hex_data):
    data = bytes.fromhex(hex_data)
    attribute_type, total_size = struct.unpack("<II", data[:8])
    times = [filetime_to_dt(struct.unpack("<Q", data[i:i+8])[0]) for i in range(24, 56, 8)]
    print("Attribute Type: " + str(attribute_type))
    print("Total Size: " + str(total_size))
    print("Creation Time: " + str(times[0]))
    print("Modification Time: " + str(times[1]))
    print("MFT Modified Time: " + str(times[2]))
    print("Last Access Time: " + str(times[3]) + "\n")
    return 0
# processing attribute $FILE_NAME
def hex_to_text(hex_string):
    hex_string = hex_string[66*2:]
    bytes_data = bytes.fromhex(hex_string)
    utf16_string = bytes_data.decode('utf-16')
    return utf16_string
# offset calculation
def byte_offset(record_string):
    attribute_offset_string = (record_string[14] + record_string[15] + record_string[12] + record_string[13]+
                               record_string[10]+record_string[11]+record_string[8]+record_string[9])
    attribute_offset = int(attribute_offset_string, 16)
    atribute = record_string[: attribute_offset * 2]
    record_string = (record_string[attribute_offset * 2:])
    return record_string, atribute
# processing resident attribute $DATA
def data_file (attribute):
    offset = attribute[20 * 2:21 * 2]
    offset_dec = int(offset, 16)
    attribute_data = attribute[offset_dec * 2:]
    ascii_text = binascii.unhexlify(attribute_data).decode('utf-8', 'ignore')
    print("File content:")
    print(ascii_text)
    return 0

# file table processing
disk = pytsk3.Img_Info(args.image_path)
cluster_size = size_cluster(args.image_path)
fs = pytsk3.FS_Info(disk)
mft_entry = fs.open("/$MFT")
data = mft_entry.read_random(0, mft_entry.info.meta.size)
mft_record_size = 1024
hex_data = binascii.hexlify(data)
records = [hex_data[i:i+mft_record_size*2] for i in range(0, len(hex_data), mft_record_size*2)]
type_id = {16: "$STANDARD_INFORMATION", 32: "$ATTRIBUTE_LIST",  48: "$FILE_NAME", 64: "VOLUME_VERSION",
           80: "$SECURITY_DESCRIPTOR", 96: "$VOLUME_NAME", 112: "$VOLUME_INFORMATION", 128: "$DATA",
           144: "$INDEX_ROOT", 160: "$INDEX_ALLOCATION", 176: "$BITMAP", 192: "$SYMBOLIC_LINK"}

i = 0
r = 0
# file record processing
for record in records:
    if i >= 24:
        record_string = str(record)
        record_string = record_string[2:]
        b = record_string[46] + record_string[47] + record_string[44] + record_string[45]
        if b == "0000":
            print("\n----DELETED FILE #" + str(r) + "----\n")
            r += 1
            print("Number of MFT record: "+str(i) + "\n")
            attribute_offset_string = record_string[42] + record_string[43] + record_string[40] + record_string[41]
            attribute_offset = int(attribute_offset_string, 16)
            record_string = (record_string[attribute_offset * 2:])
            print("Attributes info:\n")
            while record_string[:8] != 'ffffffff':
                attribute_id = record_string[2] + record_string[3] + record_string[0] + record_string[1]
                attribute_id_number = int(attribute_id, 16)
                print('Attrbiute ' + type_id[attribute_id_number] + " - " + str(attribute_id_number))
                record_string, attribute = byte_offset(record_string)
                if attribute_id_number == 16:
                    standard_information(attribute)
                if attribute_id_number == 48:
                    print("Deleted file name:" + hex_to_text(attribute) + "\n")
                if attribute_id_number == 128:
                    flag = attribute[8 * 2:9 * 2]
                    if flag == "00":
                        print("Attribute form: resident")
                        data_file(attribute)
                    else:
                        # processing non-resident attribute $DATA
                        print("Attribute form: non-resident")
                        size_data = attribute[16 * 2:18 * 2]
                        data_attribute = bytes.fromhex(attribute)
                        runlist_offset = struct.unpack('<H', data_attribute[32:34])[0]
                        runlist_data = data_attribute[runlist_offset:]
                        runlist = p_runlist(runlist_data)
                        print("File content:")
                        for start, end in runlist:
                            while start < end:
                                cluster_data = read_cluster(args.image_path, start, cluster_size)
                                print(cluster_data.decode('utf-8', errors='ignore'))
                                start += 1
    i += 1
