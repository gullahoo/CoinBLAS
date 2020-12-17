from pathlib import Path
from psycopg2.extras import execute_values

from pygraphblas import UINT64

from coinblas.util import (
    curse,
    get_block_number,
    query,
    maximal_matrix,
    lazy,
)


class Block:
    def __init__(self, chain, number, hash=None):
        self.chain = chain
        self.id = number << 32
        self.number = number
        if hash is not None:
            self.hash = hash

    @classmethod
    def from_id(cls, chain, id):
        return Block(chain, get_block_number(id))

    @classmethod
    def bq_insert(cls, chain, bq):
        b = Block(chain, bq.number, bq.hash)
        b.insert(bq)
        return b

    @lazy
    def pending_txs(self):
        return []

    @lazy
    def pending_addrs(self):
        return []

    @lazy
    def BT(self):
        return maximal_matrix(UINT64)

    @lazy
    def IT(self):
        return maximal_matrix(UINT64)

    @lazy
    def TO(self):
        return maximal_matrix(UINT64)

    @lazy
    @curse
    @query
    def hash(self, curs):
        """
        SELECT b_hash FROM bitcoin.base_block WHERE b_number = {self.number}
        """
        return curs.fetchone()[0]

    @lazy
    @curse
    @query
    def timestamp(self, curs):
        """
        SELECT b_timestamp FROM bitcoin.base_block WHERE b_number  = {self.number}
        """
        return curs.fetchone()[0]

    @lazy
    def tx_vector(self):
        return self.chain.BT[self.id, :]

    @curse
    def insert(self, curs, bq):
        curs.execute(
            """
        INSERT INTO bitcoin.base_block 
            (b_number, b_hash, b_timestamp, b_timestamp_month)
        VALUES 
            (%s, %s, %s, %s)
        """,
            (self.number, self.hash, bq.timestamp, bq.timestamp_month),
        )

    @curse
    @query
    def finalize(self, curs, month):
        """
        UPDATE bitcoin.base_block SET b_imported_at = now()
        WHERE b_number = {self.number}
        """
        month = str(month).replace("-", "_")
        execute_values(
            curs,
            f"""
            INSERT INTO bitcoin."base_tx_{month}" (t_id, t_hash) VALUES %s
            """,
            self.pending_txs,
        )
        execute_values(
            curs,
            f"""
            INSERT INTO bitcoin."base_output_{month}" (o_address, o_id) VALUES %s
            """,
            self.pending_addrs,
        )
        execute_values(
            curs,
            f"""
        UPDATE bitcoin.base_block 
            SET b_addresses = s.agg
            FROM (SELECT hll_add_agg(hll_hash_bigint(v.id)) as agg 
                  FROM (VALUES %s) v(id)) s
        WHERE b_number = {self.number}
            """,
            [(a[1],) for a in self.pending_addrs],
        )
        self.write_block_files(self.chain.block_path)

    def add_tx(self, tx):
        self.pending_txs.append((tx.id, tx.hash))

    def add_address(self, address, o_id):
        self.pending_addrs.append((address, o_id))

    def write_block_files(self, path):
        b = Path(path) / Path(self.hash[-2]) / Path(self.hash[-1])
        b.mkdir(parents=True, exist_ok=True)
        BTf = b / Path(f"{self.number}_{self.hash}_BT.ssb")
        ITf = b / Path(f"{self.number}_{self.hash}_IT.ssb")
        TOf = b / Path(f"{self.number}_{self.hash}_TO.ssb")

        self.BT.to_binfile(bytes(BTf))
        self.IT.to_binfile(bytes(ITf))
        self.TO.to_binfile(bytes(TOf))

    def __iter__(self):
        from .tx import Tx

        for t_id, _ in self.tx_vector:
            yield Tx(self.chain, id=t_id)

    def __repr__(self):
        return f"<Block: {self.number}>"
