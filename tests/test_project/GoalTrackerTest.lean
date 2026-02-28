import Mathlib

-- 1. Clean theorem (no sorry, no unusual axioms)
theorem gt_clean : 1 + 1 = 2 := by norm_num

-- 2. Direct sorry in a theorem
theorem gt_direct_sorry : 1 + 1 = 3 := by sorry

-- 3. Clean def used by a clean theorem
def gt_helper : Nat := 42
theorem gt_uses_clean_helper : gt_helper = 42 := by rfl

-- 4. Sorry def used transitively by a theorem
def gt_sorry_def : Nat := by exact sorry
theorem gt_transitive_sorry : gt_sorry_def = 42 := by sorry

-- 5. Chain: A uses B uses C (sorry) — 2-level transitive sorry
def gt_level2_sorry : Nat := by exact sorry
def gt_level1 : Nat := gt_level2_sorry + 1
theorem gt_chain_sorry : gt_level1 > 0 := by sorry

-- 6. Clean theorem depending on Decidable (uses standard axioms only)
theorem gt_decidable : ∀ n : Nat, n = n ∨ n ≠ n := by
  intro n; left; rfl

-- 7. noncomputable def (uses Classical.choice axiom, but no sorry)
noncomputable def gt_noncomputable : Nat := Classical.choice ⟨0⟩
theorem gt_uses_noncomputable : gt_noncomputable = gt_noncomputable := by rfl

-- 8. Explicit sorry in term mode
def gt_term_sorry : Nat := sorry

-- 9. Theorem that depends on term-mode sorry transitively
theorem gt_uses_term_sorry : gt_term_sorry = gt_term_sorry := by rfl

-- 10. Multiple sorry sources converging
def gt_sorry_a : Nat := sorry
def gt_sorry_b : Bool := sorry
theorem gt_multi_sorry : gt_sorry_a = gt_sorry_a ∧ gt_sorry_b = gt_sorry_b := by
  exact ⟨rfl, rfl⟩

-- 11. Diamond: shared sorry dep reached through two paths
def gt_shared_sorry : Nat := sorry
def gt_path_left : Nat := gt_shared_sorry + 1
def gt_path_right : Nat := gt_shared_sorry + 2
theorem gt_diamond : gt_path_left + gt_path_right > 0 := by sorry

-- 12. Namespaced declarations for name resolution testing
namespace GtNs
theorem ns_clean : 1 + 1 = 2 := by norm_num
theorem ns_sorry : 1 + 1 = 3 := by sorry
private def ns_private_sorry : Nat := sorry
theorem ns_uses_private : ns_private_sorry = ns_private_sorry := by rfl
end GtNs

-- 13. Nested namespaces
namespace GtOuter
namespace GtInner
theorem nested_sorry : False := by sorry
end GtInner
end GtOuter

-- 14. Section (should not affect FQN)
section GtSection
theorem gt_in_section : 1 + 1 = 2 := by norm_num
end GtSection
