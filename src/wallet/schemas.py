import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

from src.wallet.models import TransactionStatus, TransactionType, WalletStatus


class WalletResponse(BaseModel):
    id: uuid.UUID
    balance: Decimal
    currency: str
    status: WalletStatus
    updated_at: datetime

    model_config = {"from_attributes": True}


class DepositRequest(BaseModel):
    amount: Decimal = Field(gt=0, decimal_places=2)
    currency: str = "BRL"
    description: str | None = None


class PixDestination(BaseModel):
    type: Literal["pix"] = "pix"
    key: str = Field(min_length=1, description="PIX key (CPF, CNPJ, e-mail, phone, or random key)")


class BankAccountDestination(BaseModel):
    type: Literal["bank_account"] = "bank_account"
    bank_code: str = Field(min_length=3, max_length=3, description="Bank code (e.g. 001)")
    branch: str = Field(min_length=1, description="Branch number (agência)")
    account_number: str = Field(min_length=1, description="Account number")
    account_digit: str | None = Field(default=None, description="Account check digit")
    account_type: Literal["checking", "savings"] = "checking"
    holder_document: str | None = Field(default=None, description="CPF or CNPJ of the account holder")
    holder_name: str | None = None


WithdrawDestination = Annotated[
    PixDestination | BankAccountDestination,
    Field(discriminator="type"),
]


class WithdrawRequest(BaseModel):
    amount: Decimal = Field(gt=0, decimal_places=2)
    destination: WithdrawDestination
    description: str | None = None


class TransferRequest(BaseModel):
    amount: Decimal = Field(gt=0, decimal_places=2)
    recipient_email: str | None = None
    recipient_id: uuid.UUID | None = None
    description: str | None = None

    @model_validator(mode="after")
    def validate_recipient(self) -> "TransferRequest":
        """Require exactly one recipient identifier: email or user id."""
        has_email = self.recipient_email is not None
        has_id = self.recipient_id is not None
        if has_email == has_id:
            raise ValueError("Exactly one of recipient_email or recipient_id must be provided")
        return self


class TransactionResponse(BaseModel):
    id: uuid.UUID
    type: TransactionType
    amount: Decimal
    status: TransactionStatus
    description: str | None
    counterpart_transaction_id: uuid.UUID | None
    gateway_reference: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class TransactionListResponse(BaseModel):
    items: list[TransactionResponse]
    total: int
    page: int
    page_size: int
