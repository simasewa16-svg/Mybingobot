"""Initial schema with ledger, refund, and payout protection

Revision ID: 001_initial
Revises: 
Create Date: 2026-10-13

✅ ይህ migration የሚከተሉትን ይፈጥራል፦
- users ሠንጠረዥ (is_banned, check constraint)
- games ሠንጠረዥ (refunded, payout_completed, rollover_jackpot, partial index)
- cards ሠንጠረዥ (refunded, price_paid, unique constraint)
- transactions ሠንጠረዥ
- audit_logs ሠንጠረዥ
- ledger_entries ሠንጠረዥ (unique constraint)
"""
from alembic import op
import sqlalchemy as sa


revision = '001_initial'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ================================================================
    # ✅ 1. users ሠንጠረዥ
    # ================================================================
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('telegram_id', sa.String(), nullable=False),
        sa.Column('username', sa.String(), nullable=True),
        sa.Column('balance', sa.Numeric(12, 2), server_default='0.00', nullable=False),
        sa.Column('is_banned', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint('balance >= 0', name='ck_user_balance_non_negative'),
    )
    op.create_index('ix_users_telegram_id', 'users', ['telegram_id'], unique=True)

    # ================================================================
    # ✅ 2. games ሠንጠረዥ
    # ================================================================
    op.create_table(
        'games',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('status', sa.String(), nullable=False, server_default='waiting'),
        sa.Column('jackpot', sa.Numeric(12, 2), server_default='0.00', nullable=False),
        sa.Column('card_price', sa.Numeric(12, 2), server_default='10.00', nullable=False),
        sa.Column('call_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('called_numbers', sa.Text(), server_default='', nullable=False),
        sa.Column('last_number', sa.Integer(), nullable=True),
        sa.Column('last_drawn_at', sa.DateTime(), nullable=True),
        sa.Column('winner_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('refunded', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('payout_completed', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('rollover_jackpot', sa.Numeric(12, 2), server_default='0.00', nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    # ✅ Partial Unique Index - አንድ ንቁ ጨዋታ ብቻ
    op.execute("""
        CREATE UNIQUE INDEX uq_single_active_game 
        ON games ((status IN ('waiting','playing'))) 
        WHERE status IN ('waiting','playing')
    """)

    # ================================================================
    # ✅ 3. cards ሠንጠረዥ
    # ================================================================
    op.create_table(
        'cards',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('game_id', sa.Integer(), sa.ForeignKey('games.id'), nullable=False),
        sa.Column('numbers', sa.Text(), nullable=False),
        sa.Column('is_winner', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('price_paid', sa.Numeric(12, 2), server_default='10.00', nullable=False),
        sa.Column('refunded', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('refunded_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('user_id', 'game_id', name='uq_user_game_card'),
    )
    op.create_index('ix_cards_user_id', 'cards', ['user_id'])
    op.create_index('ix_cards_game_id', 'cards', ['game_id'])

    # ================================================================
    # ✅ 4. transactions ሠንጠረዥ
    # ================================================================
    op.create_table(
        'transactions',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('amount', sa.Numeric(12, 2), nullable=False),
        sa.Column('method', sa.String(), nullable=False),
        sa.Column('status', sa.String(), server_default='pending', nullable=False),
        sa.Column('reference', sa.String(), nullable=False),
        sa.Column('reviewed_by', sa.String(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint('amount > 0', name='ck_transaction_amount_positive'),
    )
    op.create_index('ix_transactions_user_id', 'transactions', ['user_id'])
    op.create_index('ix_transactions_reference', 'transactions', ['reference'], unique=True)
    op.create_index('ix_transactions_created_at', 'transactions', ['created_at'])

    # ================================================================
    # ✅ 5. audit_logs ሠንጠረዥ
    # ================================================================
    op.create_table(
        'audit_logs',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('actor_id', sa.String(), nullable=False),
        sa.Column('action', sa.String(), nullable=False),
        sa.Column('target_type', sa.String(), nullable=True),
        sa.Column('target_id', sa.String(), nullable=True),
        sa.Column('details', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_audit_logs_actor_id', 'audit_logs', ['actor_id'])
    op.create_index('ix_audit_logs_action', 'audit_logs', ['action'])
    op.create_index('ix_audit_logs_created_at', 'audit_logs', ['created_at'])

    # ================================================================
    # ✅ 6. ledger_entries ሠንጠረዥ (ዋናው የደህንነት ክፍል)
    # ================================================================
    op.create_table(
        'ledger_entries',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('entry_type', sa.String(), nullable=False),
        sa.Column('amount', sa.Numeric(12, 2), nullable=False),
        sa.Column('balance_after', sa.Numeric(12, 2), nullable=False),
        sa.Column('reference_type', sa.String(), nullable=True),
        sa.Column('reference_id', sa.String(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            'user_id', 'entry_type', 'reference_type', 'reference_id',
            name='uq_ledger_no_duplicate'
        ),
    )
    op.create_index('ix_ledger_entries_user_id', 'ledger_entries', ['user_id'])
    op.create_index('ix_ledger_entries_entry_type', 'ledger_entries', ['entry_type'])
    op.create_index('ix_ledger_entries_created_at', 'ledger_entries', ['created_at'])


def downgrade() -> None:
    """
    ⚠️ አደጋ! ይህ ተግባር ሁሉንም ሠንጠረዦች ያጠፋል!
    በ Production ላይ ፈጽሞ አታስኪድ/ጂው!
    """
    op.drop_index('ix_ledger_entries_created_at', 'ledger_entries')
    op.drop_index('ix_ledger_entries_entry_type', 'ledger_entries')
    op.drop_index('ix_ledger_entries_user_id', 'ledger_entries')
    op.drop_table('ledger_entries')

    op.drop_index('ix_audit_logs_created_at', 'audit_logs')
    op.drop_index('ix_audit_logs_action', 'audit_logs')
    op.drop_index('ix_audit_logs_actor_id', 'audit_logs')
    op.drop_table('audit_logs')

    op.drop_index('ix_transactions_created_at', 'transactions')
    op.drop_index('ix_transactions_reference', 'transactions')
    op.drop_index('ix_transactions_user_id', 'transactions')
    op.drop_table('transactions')

    op.drop_index('ix_cards_game_id', 'cards')
    op.drop_index('ix_cards_user_id', 'cards')
    op.drop_table('cards')

    op.execute("DROP INDEX IF EXISTS uq_single_active_game")
    op.drop_table('games')

    op.drop_index('ix_users_telegram_id', 'users')
    op.drop_table('users')
