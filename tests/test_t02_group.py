from pathlib import Path
import pandas as pd
import pytest
from src.common.io import resolve_config
from src.common.context import RunContext
from src.common.review import AuditLog
from src.pipeline import run


def test_t02_pipeline_output_contract():
    """Kiểm tra contract file output của nhóm (success test)."""
    pred_path = Path("out/ranked_review.csv")
    assert pred_path.exists(), "ranked_review.csv chua duoc sinh ra"
    df = pd.read_csv(pred_path)
    
    # Contract bắt buộc phải có đủ cột
    assert "image_id" in df.columns
    assert "score" in df.columns
    assert len(df) == 96, "Tong so anh phai bang 96"
    
    # Kiểm tra tính toàn vẹn: không có NaN, điểm nằm trong [0, 1]
    assert not df["score"].isna().any(), "Khong duoc chua gia tri NaN trong score"
    assert (df["score"] >= 0.0).all() and (df["score"] <= 1.0).all(), "Score phai trong doan [0, 1]"
    
    # Sắp xếp giảm dần theo điểm nghi lỗi
    scores = df["score"].tolist()
    assert scores == sorted(scores, reverse=True), "Scores phai duoc sap xep giam dan"


def test_t02_review_overrides_and_audit():
    """Kiểm tra Human-in-the-loop: override va audit log duoc ghi nhan day du."""
    audit_file = Path("out/audit_log.jsonl")
    assert audit_file.exists(), "audit_log.jsonl phai ton tai sau khi review"
    
    audit_log = AuditLog(audit_file)
    events = audit_log.read()
    assert len(events) > 0, "Audit log phai ghi nhan it nhat 1 su kien override"
    
    # Kiem tra quyet dinh reject anh img_07_2 duoc ghi de sang KEEP
    pred_df = pd.read_csv("out/ranked_review.csv")
    row_07_2 = pred_df[pred_df["image_id"] == "img_07_2"]
    assert not row_07_2.empty
    assert row_07_2["pred_action"].iloc[0] == "KEEP", "img_07_2 phai duoc cap nhat thanh KEEP theo review"


def test_t02_night_images_guardrail():
    """Edge case: Kiem tra anh ban dem binh thuong khong bi danh nham la dark defect."""
    pred_df = pd.read_csv("out/ranked_review.csv")
    # img_01_0 va img_01_1 la anh ban dem binh thuong (khong loi)
    night_cleans = pred_df[pred_df["image_id"].isin(["img_01_0", "img_01_1"])]
    for _, row in night_cleans.iterrows():
        assert row["pred_defect_type"] != "dark", f"{row['image_id']} khong duoc bi bao nham la dark defect"
