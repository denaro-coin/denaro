import asyncio
from os import environ
from dotenv import load_dotenv
load_dotenv('.env')

from asyncpg import UndefinedTableError

from denaro import Database


async def run():
    db: Database = await Database.create(
        user=environ.get('DENARO_DATABASE_USER', 'denaro'),
        password=environ.get('DENARO_DATABASE_PASSWORD', ''),
        database=environ.get('DENARO_DATABASE_NAME', 'denaro'),
        host=environ.get('DENARO_DATABASE_HOST', None),
        ignore=True
    )
    async with db.pool.acquire() as connection:
        try:
            res = await connection.fetchrow('SELECT * FROM unspent_outputs WHERE true LIMIT 1')
            if res is not None:
                print('Unspent outputs table already exist')
                exit()
        except UndefinedTableError:
            print('Creating table unspent_outputs and type tx_output')
            await connection.execute("""
                CREATE TYPE tx_output AS (
                    tx_hash CHAR(64),
                    index SMALLINT
                );

                CREATE TABLE IF NOT EXISTS unspent_outputs (
                    tx_hash CHAR(64) REFERENCES transactions(tx_hash) ON DELETE CASCADE,
                    index SMALLINT NOT NULL
                );"""
            )
            print('Created')
    print('Retrieving outputs... This will take a few minutes')
    unspent_outputs = await db.get_unspent_outputs_from_all_transactions()
    print(f'Found {len(unspent_outputs)} outputs. Adding them...')
    await db.add_unspent_outputs(unspent_outputs)
    print('Done.')


loop = asyncio.get_event_loop()
loop.run_until_complete(run())

