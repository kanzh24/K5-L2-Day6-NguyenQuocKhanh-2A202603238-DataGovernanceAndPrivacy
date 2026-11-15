"""PoC Pipeline for Track T02: Raw QC Triage."""
from __future__ import annotations

from pathlib import Path
import pandas as pd
import numpy as np

from .common.context import RunContext
from .common.decision import Decision, write_decision
from .common.manifest import verify_manifest
from .common.review import apply_overrides, load_review_decisions, make_review_queue, write_review_queue
from .common.contact_sheet import render_contact_sheet
from .common.image_ops import load_rgb, laplacian_variance, brightness_stats
from .metrics.tracks import get_track


# ---------------------------------------------------------------- 01 load
def load(ctx: RunContext) -> dict:
    if ctx.track != "t02":
        raise NotImplementedError(f"Track {ctx.track} is not implemented yet in this PoC pipeline.")

    manifest = ctx.input_dir / "manifest.csv"
    problems = verify_manifest(manifest) if manifest.exists() else [{"problem": "no_manifest"}]
    if problems:
        ctx.audit.log(actor="pipeline", action="provenance_problems", item_id=str(manifest), after=problems[:20])
        if ctx.config.get("strict_provenance", True):
            raise ValueError(f"provenance check failed ({len(problems)} problems), first: {problems[:3]}")

    images_csv = ctx.input_dir / "images.csv"
    if not images_csv.exists():
        raise FileNotFoundError(f"Missing {images_csv}")
    
    images_df = pd.read_csv(images_csv)
    return {"manifest": pd.read_csv(manifest) if manifest.exists() else None, "images": images_df}


# ---------------------------------------------------------------- 02 process
def process(ctx: RunContext, data: dict) -> pd.DataFrame:
    df = data["images"].copy()
    
    records = []
    for _, row in df.iterrows():
        img_id = row["image_id"]
        img_path = ctx.input_dir / row["path"]
        cam = row.get("camera_id", "cam_A")
        light = row.get("light", "day")
        
        # 1. Trích xuất đặc trưng vật lý ảnh
        img = load_rgb(img_path)
        lap = laplacian_variance(img)
        b_stats = brightness_stats(img)
        file_size = img_path.stat().st_size
        
        # 2. Chấm điểm từng loại khuyết tật (0 = tốt, 1 = lỗi nghiêm trọng)
        # 2a. Blur score: chuẩn hóa theo camera_id
        blur_baseline = 600.0 if cam == "cam_A" else 250.0
        score_blur = float(np.clip(1.0 - (lap / blur_baseline), 0.0, 1.0))
        
        # 2b. Dark score: tránh bẫy ảnh ban đêm
        if light == "night":
            score_dark = float(np.clip(1.0 - (b_stats["mean"] / 15.0), 0.0, 1.0)) if b_stats["mean"] < 15.0 else 0.0
        else:
            score_dark = float(np.clip(1.0 - (b_stats["mean"] / 40.0), 0.0, 1.0))
            
        # 2c. Glare score: tỷ lệ điểm cháy sáng (saturated pixels)
        score_glare = float(np.clip(b_stats["frac_saturated"] / 0.05, 0.0, 1.0))
        if b_stats["mean"] > 160.0:
            score_glare = max(score_glare, 0.8)
            
        # 2d. Compression score: file nén JPEG quá mức dẫn đến dung lượng rất bé
        score_comp = float(np.clip(1.0 - (file_size / 4500.0), 0.0, 1.0)) if file_size < 4500 else 0.0
        
        # 3. Tổng hợp thành defect score cao nhất và xác định loại lỗi
        sub_scores = {
            "blur": score_blur,
            "dark": score_dark,
            "glare": score_glare,
            "compression": score_comp
        }
        best_defect = max(sub_scores, key=sub_scores.get)
        final_score = sub_scores[best_defect]
        
        pred_action = "RECAPTURE" if final_score >= 0.5 else "KEEP"
        pred_type = best_defect if final_score >= 0.5 else "none"
        
        records.append({
            "image_id": img_id,
            "score": round(final_score, 4),
            "pred_defect_type": pred_type,
            "pred_action": pred_action,
            "reason": f"Defect: {best_defect} (score: {round(final_score, 2)})" if final_score >= 0.5 else "OK",
            "evidence_path": str(row["path"]),
            "camera_id": cam,
            "light": light
        })

    result_df = pd.DataFrame(records)
    # Sắp xếp điểm nghi lỗi từ cao xuống thấp
    result_df = result_df.sort_values("score", ascending=False).reset_index(drop=True)
    return result_df


# ---------------------------------------------------------------- 03 rank
def rank(ctx: RunContext, scored: pd.DataFrame) -> pd.DataFrame:
    budget = int(ctx.param("budget", 20))
    q = make_review_queue(
        scored,
        id_col="image_id",
        score_col="score",
        budget=budget,
        reason_col="reason",
        action_col="pred_action",
        evidence_col="evidence_path"
    )
    write_review_queue(q, ctx.out("review_queue.csv"))
    return q


# ---------------------------------------------------------------- 04 review
def review(ctx: RunContext, scored: pd.DataFrame, queue: pd.DataFrame) -> pd.DataFrame:
    # Xuất contact sheet HTML để người dùng review trực quan
    render_contact_sheet(
        queue,
        ctx.out("contact_sheet.html"),
        image_root=ctx.input_dir,
        title=f"T02 QC Triage Review Queue (Top {len(queue)})"
    )
    
    # Kiểm tra xem có file ghi nhận chỉnh sửa từ reviewer không
    reviewed_path = ctx.output_dir / "review_queue_reviewed.csv"
    if reviewed_path.exists():
        reviewed = load_review_decisions(reviewed_path)
        ctx.stats["n_reviewed"] = len(reviewed)
        
        # 1. Áp dụng ghi đè loại lỗi khi reviewer chọn 'edit' (ví dụ sửa blur thành dark)
        scored = apply_overrides(scored, reviewed, id_col="image_id", value_col="pred_defect_type", audit=ctx.audit)
        
        # 2. Xử lý khi reviewer chọn 'reject' (bác bỏ đề xuất lỗi -> chuyển sang KEEP và none)
        for r in reviewed.itertuples(index=False):
            if r.reviewer_decision == "reject":
                mask = scored["image_id"] == r.item_id
                old_action = scored.loc[mask, "pred_action"].tolist()
                scored.loc[mask, "pred_action"] = "KEEP"
                scored.loc[mask, "pred_defect_type"] = "none"
                if ctx.audit:
                    ctx.audit.log(
                        actor=r.reviewer,
                        action="override:reject",
                        item_id=r.item_id,
                        before=old_action[0] if old_action else "RECAPTURE",
                        after="KEEP",
                        reason=r.review_note
                    )
    return scored


# ---------------------------------------------------------------- 05 decide
def decide(ctx: RunContext, final: pd.DataFrame) -> Decision:
    defect_count = (final["pred_action"] == "RECAPTURE").sum()
    defect_rate = defect_count / max(1, len(final))
    owner = ctx.config.get("owner", "Nguyen Quoc Khanh - leader")
    
    # Chính sách: Nếu tỷ lệ ảnh lỗi > 15%, tạm giữ lại (HOLD) để kiểm định kỹ thuật
    if defect_rate > 0.15:
        return Decision(
            status="HOLD",
            reason_code="HIGH_DEFECT_RATE",
            reason=f"Phat hien {defect_count}/{len(final)} anh khuyet tat ({defect_rate:.1%}), vuot nguong 15%",
            owner=owner,
            scope=ctx.track,
            evidence=[str(ctx.out("ranked_review.csv")), str(ctx.out("review_queue.csv"))],
            metrics={"defect_count": int(defect_count), "defect_rate": round(defect_rate, 4)}
        )
    return Decision(
        status="GO",
        reason_code="QC_PASSED",
        reason="Chat luong anh du tieu chuan release",
        owner=owner,
        scope=ctx.track,
        evidence=[str(ctx.out("ranked_review.csv"))]
    )


def run(ctx: RunContext) -> None:
    spec = get_track(ctx.track)
    data = load(ctx)
    scored = process(ctx, data)
    ctx.stats["n_items"] = len(scored)
    
    queue = rank(ctx, scored)
    final = review(ctx, scored, queue)
    
    # Ghi file kết quả dự đoán ranked_review.csv (bắt buộc đúng contract)
    pred_path = ctx.out(spec.pred_file)
    cols = spec.pred_columns + [c for c in ["pred_defect_type", "pred_action"] if c in final.columns]
    final[cols].to_csv(pred_path, index=False)
    
    # Ghi quyết định phát hành
    decision = decide(ctx, final)
    write_decision(decision, ctx.out("decision.json"), ctx.out("decision_log.csv"))