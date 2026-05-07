import ggwave

CHUNK_SIZE = 1024  # number of float32 samples per chunk
BYTES_PER_SAMPLE = 4  # float32 = 4 bytes

print("Reading from file...")

instance = ggwave.init()

with open("integration.raw", "rb") as f:
    i = 0

    try:
        while True:
            print(f"Chunk #{i}")
            i += 1

            data = f.read(CHUNK_SIZE * BYTES_PER_SAMPLE)

            if not data:
                break  # EOF

            res = ggwave.decode(instance, data)

            if res is not None:
                try:
                    print(f"Received text: {res.decode("utf-8")}")
                except Exception as e:
                    print(e)

    except KeyboardInterrupt:
        print("Stopping...")

ggwave.free(instance)
