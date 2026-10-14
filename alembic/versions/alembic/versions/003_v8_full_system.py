"""Add multi-admin, withdrawal, player management, fraud flags

Revision ID: 003_v8_full_system
Revises: 002_v6_5_schema
Create Date: 2026-10-15

✅ ይህ migration የሚያክለው፦
   1. users: first_name, last_name, is_flagged, notes, last_active
   2. transactions: notes
   3. audit_logs: actor_username, actor_role, ip_address
   4. ledger_entries CHECK constraints ማስፋፋት
   5. withdrawals (አዲስ ሠንጠረዥ)
   6. admin_users (አዲስ ሠንጠረዥ)
   7. player_notes (አዲስ ሠንጠረዥ)
   8. fraud_flags (አዲስ ሠንጠረዥ)
   9. games.is_test_game
"""
from alembic import op
import sqlalchemy as sa


revision = '003_v8_full_system'
down_revision = '002_v6_5_schema'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ============================================================
    # ✅ 1. users — አዲስ columns
    # ============================================================
    op.add_column('users', sa.Column('first_name', sa.String(255), nullable=True))
    op.add_column('users', sa.Column('last_name', sa.String(255), nullable=True))
    op.add_column('users', sa.Column(
        'is_flagged', sa.Boolean(),
        server_default=sa.text('false'), nullable=False
    ))
    op.add_column('users', sa.Column('notes', sa.Text(), nullable=True))
    op.add_column('users', sa.Column(
        'last_active', sa.DateTime(timezone=True), nullable=True
    ))

    # ============================================================
    # ✅ 2. transactions — notes
    # ============================================================
    op.add_column('transactions', sa.Column('notes', sa.Text(), nullable=True))

    # ============================================================
    # ✅ 3. audit_logs — actor info
    # ============================================================
    op.add_column('audit_logs', sa.Column(
        'actor_username', sa.String(255), nullable=True
    ))
    op.add_column('audit_logs', sa.Column(
        'actor_role', sa.String(20), nullable=True
    ))
    op.add_column('audit_logs', sa.Column(
        'ip_address', sa.String(50), nullable=True
    ))

    # ============================================================
    # ✅ 4. games — is_test_game
    # ============================================================
    op.add_column('games', sa.Column(
        'is_test_game', sa.Boolean(),
        server_default=sa.text('false'), nullable=False
    ))

    # ============================================================
    # ✅ 5. ledger_entries — CHECK constraints ማስፋፋት
    # ============================================================
    op.drop_constraint('ck_ledger_entry_type_valid', 'ledger_entries', type_='check')
    op.drop_constraint('ck_ledger_reference_type_valid', 'ledger_entries', type_='check')

    op.create_check_constraint(
        'ck_ledger_entry_type_valid', 'ledger_entries',
        "entry_type IN ("
        "'deposit_approved','card_purchase','prize_payout','refund',"
        "'withdrawal_pending','withdrawal_refund','admin_adjustment'"
        ")"
    )
    op.create_check_constraint(
        'ck_ledger_reference_type_valid', 'ledger_entries',
        "reference_type IN ('transaction','card','game','withdrawal','admin','system')"
    )

    # ============================================================
    # ✅ 6. withdrawals — አዲስ ሠንጠረዥ
    # ============================================================
    op.create_table(
        'withdrawals',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('amount', sa.Numeric(12, 2), nullable=False),
        sa.Column('method', sa.String(50), nullable=False),
        sa.Column('account_number', sa.String(100), nullable=False),
        sa.Column('account_name', sa.String(255), nullable=True),
        sa.Column('status', sa.String(20), server_default='pending', nullable=False),
        sa.Column('reference', sa.String(100), nullable=True),
        sa.Column('reviewed_by', sa.String(50), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint('amount > 0', name='ck_withdrawal_amount_positive'),
        sa.CheckConstraint(
            "status IN ('pending','approved','rejected')",
            name='ck_withdrawal_status_valid'
        ),
        sa.CheckConstraint(
            "method IN ('ቴሌብር','ሲቢኢ ብር')",
            name='ck_withdrawal_method_valid'
        ),
    )
    op.create_index('ix_withdrawals_user_id', 'withdrawals', ['user_id'])
    op.create_index('ix_withdrawals_status', 'withdrawals', ['status'])
    op.create_index('ix_withdrawals_created_at', 'withdrawals', ['created_at'])

    # ============================================================
    # ✅ 7. admin_users — አዲስ ሠንጠረዥ
    # ============================================================
    op.create_table(
        'admin_users',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('telegram_id', sa.String(50), nullable=False),
        sa.Column('username', sa.String(255), nullable=True),
        sa.Column('display_name', sa.String(255), nullable=False),
        sa.Column('role', sa.String(20), server_default='sub_admin', nullable=False),
        sa.Column('permissions', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(),
                  server_default=sa.text('true'), nullable=False),
        sa.Column('created_by', sa.String(50), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column('last_login', sa.DateTime(timezone=True), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.CheckConstraint(
            "role IN ('super_admin','sub_admin','finance_admin','moderator','viewer')",
            name='ck_admin_role_valid'
        ),
    )
    op.create_index('ix_admin_users_telegram_id', 'admin_users',
                    ['telegram_id'], unique=True)
    op.create_index('ix_admin_users_role', 'admin_users', ['role'])

    # ============================================================
    # ✅ 8. player_notes — አዲስ ሠንጠረዥ
    # ============================================================
    op.create_table(
        'player_notes',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('author_id', sa.String(50), nullable=False),
        sa.Column('author_name', sa.String(255), nullable=True),
        sa.Column('note', sa.Text(), nullable=False),
        sa.Column('is_warning', sa.Boolean(),
                  server_default=sa.text('false'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_player_notes_user_id', 'player_notes', ['user_id'])
    op.create_index('ix_player_notes_created_at', 'player_notes', ['created_at'])

    # ============================================================
    # ✅ 9. fraud_flags — አዲስ ሠንጠረዥ
    # ============================================================
    op.create_table(
        'fraud_flags',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('flag_type', sa.String(50), nullable=False),
        sa.Column('severity', sa.String(20), server_default='low', nullable=False),
        sa.Column('details', sa.Text(), nullable=True),
        sa.Column('is_resolved', sa.Boolean(),
                  server_default=sa.text('false'), nullable=False),
        sa.Column('resolved_by', sa.String(50), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "severity IN ('low','medium','high')",
            name='ck_fraud_severity_valid'
        ),
    )
    op.create_index('ix_fraud_flags_user_id', 'fraud_flags', ['user_id'])
    op.create_index('ix_fraud_flags_resolved', 'fraud_flags', ['is_resolved'])


def downgrade() -> None:
    # Fraud flags
    op.drop_index('ix_fraud_flags_resolved', 'fraud_flags')
    op.drop_index('ix_fraud_flags_user_id', 'fraud_flags')
    op.drop_table('fraud_flags')

    # Player notes
    op.drop_index('ix_player_notes_created_at', 'player_notes')
    op.drop_index('ix_player_notes_user_id', 'player_notes')
    op.drop_table('player_notes')

    # Admin users
    op.drop_index('ix_admin_users_role', 'admin_users')
    op.drop_index('ix_admin_users_telegram_id', 'admin_users')
    op.drop_table('admin_users')

    # Withdrawals
    op.drop_index('ix_withdrawals_created_at', 'withdrawals')
    op.drop_index('ix_withdrawals_status', 'withdrawals')
    op.drop_index('ix_withdrawals_user_id', 'withdrawals')
    op.drop_table('withdrawals')

    # Ledger CHECK — ወደ ነባሪው ተመልስ
    op.drop_constraint('ck_ledger_reference_type_valid', 'ledger_entries', type_='check')
    op.drop_constraint('ck_ledger_entry_type_valid', 'ledger_entries', type_='check')
    op.create_check_constraint(
        'ck_ledger_entry_type_valid', 'ledger_entries',
        "entry_type IN ('deposit_approved','card_purchase','prize_payout','refund')"
    )
    op.create_check_constraint(
        'ck_ledger_reference_type_valid', 'ledger_entries',
        "reference_type IN ('transaction','card','game')"
    )

    # Drop columns
    op.drop_column('games', 'is_test_game')
    op.drop_column('audit_logs', 'ip_address')
    op.drop_column('audit_logs', 'actor_role')
    op.drop_column('audit_logs', 'actor_username')
    op.drop_column('transactions', 'notes')
    op.drop_column('users', 'last_active')
    op.drop_column('users', 'notes')
    op.drop_column('users', 'is_flagged')
    op.drop_column('users', 'last_name')
    op.drop_column('users', 'first_name')
