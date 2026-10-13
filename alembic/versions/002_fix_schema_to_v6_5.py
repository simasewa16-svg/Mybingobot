"""Fix schema to match models.py v6.5

Revision ID: 002_v6_5_schema
Revises: 001_initial
Create Date: 2026-10-13

✅ ይህ migration የሚያክለው/የሚያስተካክለው:
   1. games.original_jackpot (Numeric 12,2)
   2. games.rollover_received (Numeric 12,2)
   3. games.rollover_transferred (Boolean)
   4. ledger_entries.reference_type → NOT NULL
   5. ledger_entries.reference_id → NOT NULL
   6. ሁሉም CHECK constraints (game, transaction, ledger, card)
"""
from alembic import op
import sqlalchemy as sa


revision = '002_v6_5_schema'
down_revision = '001_initial'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ============================================================
    # ✅ 1. games table — አዲስ columns
    # ============================================================
    op.add_column('games', sa.Column(
        'original_jackpot', sa.Numeric(12, 2),
        nullable=False, server_default='0.00'
    ))
    op.add_column('games', sa.Column(
        'rollover_received', sa.Numeric(12, 2),
        nullable=False, server_default='0.00'
    ))
    op.add_column('games', sa.Column(
        'rollover_transferred', sa.Boolean(),
        nullable=False, server_default=sa.text('false')
    ))

    # ✅ 2. ነባር ውሂብ: original_jackpot = jackpot
    op.execute("UPDATE games SET original_jackpot = jackpot")

    # ============================================================
    # ✅ 3. ledger_entries — reference_type/id NOT NULL
    # ============================================================
    op.execute("""
        UPDATE ledger_entries 
        SET reference_type = 'game', reference_id = '0'
        WHERE reference_type IS NULL OR reference_id IS NULL
    """)
    op.alter_column('ledger_entries', 'reference_type',
                    existing_type=sa.String(), nullable=False)
    op.alter_column('ledger_entries', 'reference_id',
                    existing_type=sa.String(), nullable=False)

    # ============================================================
    # ✅ 4. games — CHECK constraints
    # ============================================================
    op.create_check_constraint(
        'ck_game_jackpot_non_negative', 'games', 'jackpot >= 0')
    op.create_check_constraint(
        'ck_game_original_jackpot_non_negative', 'games', 'original_jackpot >= 0')
    op.create_check_constraint(
        'ck_game_rollover_non_negative', 'games', 'rollover_jackpot >= 0')
    op.create_check_constraint(
        'ck_game_rollover_recv_non_negative', 'games', 'rollover_received >= 0')
    op.create_check_constraint(
        'ck_game_card_price_positive', 'games', 'card_price > 0')
    op.create_check_constraint(
        'ck_game_call_count_non_negative', 'games', 'call_count >= 0')
    op.create_check_constraint(
        'ck_game_status_valid', 'games',
        "status IN ('waiting','playing','finished','cancelled')")

    # ============================================================
    # ✅ 5. transactions — CHECK constraints
    # ============================================================
    op.create_check_constraint(
        'ck_transaction_status_valid', 'transactions',
        "status IN ('pending','approved','rejected')")
    op.create_check_constraint(
        'ck_transaction_method_valid', 'transactions',
        "method IN ('ቴሌብር','ሲቢኢ ብር')")

    # ============================================================
    # ✅ 6. ledger_entries — CHECK constraints
    # ============================================================
    op.create_check_constraint(
        'ck_ledger_entry_type_valid', 'ledger_entries',
        "entry_type IN ("
        "'deposit_approved','card_purchase','prize_payout','refund'"
        ")")
    op.create_check_constraint(
        'ck_ledger_reference_type_valid', 'ledger_entries',
        "reference_type IN ('transaction','card','game')")
    op.create_check_constraint(
        'ck_ledger_balance_non_negative', 'ledger_entries',
        'balance_after >= 0')

    # ============================================================
    # ✅ 7. cards — CHECK constraint
    # ============================================================
    op.create_check_constraint(
        'ck_card_price_positive', 'cards', 'price_paid > 0')


def downgrade() -> None:
    # Cards
    op.drop_constraint('ck_card_price_positive', 'cards', type_='check')

    # Ledger
    op.drop_constraint('ck_ledger_balance_non_negative', 'ledger_entries', type_='check')
    op.drop_constraint('ck_ledger_reference_type_valid', 'ledger_entries', type_='check')
    op.drop_constraint('ck_ledger_entry_type_valid', 'ledger_entries', type_='check')

    # Transactions
    op.drop_constraint('ck_transaction_method_valid', 'transactions', type_='check')
    op.drop_constraint('ck_transaction_status_valid', 'transactions', type_='check')

    # Games
    op.drop_constraint('ck_game_status_valid', 'games', type_='check')
    op.drop_constraint('ck_game_call_count_non_negative', 'games', type_='check')
    op.drop_constraint('ck_game_card_price_positive', 'games', type_='check')
    op.drop_constraint('ck_game_rollover_recv_non_negative', 'games', type_='check')
    op.drop_constraint('ck_game_rollover_non_negative', 'games', type_='check')
    op.drop_constraint('ck_game_original_jackpot_non_negative', 'games', type_='check')
    op.drop_constraint('ck_game_jackpot_non_negative', 'games', type_='check')

    # Ledger nullable
    op.alter_column('ledger_entries', 'reference_id',
                    existing_type=sa.String(), nullable=True)
    op.alter_column('ledger_entries', 'reference_type',
                    existing_type=sa.String(), nullable=True)

    # Drop new columns
    op.drop_column('games', 'rollover_transferred')
    op.drop_column('games', 'rollover_received')
    op.drop_column('games', 'original_jackpot')
