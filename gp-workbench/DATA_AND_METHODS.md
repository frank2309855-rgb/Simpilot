# Bundled data and method contract

## What is included

Five real **derived** S(q,t) CSVs, one seed per recipe, for Stage 1 mixing. Each row has `time,q,S`. Frames 1490–1499 are included; no earlier trajectory, raw coordinates or bonds are included. The historical 1200–1480 time window is not reproduced here.

The ratio labels 1:21, 5:17, 8:14, 11:11 and 15:7 are encoded as A/(A+B) for the GP input. Their material identities and physical counting basis remain unresolved. Type-1/type-2 bead counts differ from those labels. Do not describe the input coordinate as measured PDMS fraction without additional confirmation.

The box is 128³ in simulation length units. The original curve calculation used q_max=1 and radial dq=0.01. q is inverse simulation length; time is simulation step. No conversion to nm or seconds is claimed.

## Normalized concentration structure factor

For actual species fractions c_i=N_i/N:

`rho_i(q,t) = sum over particles of type i exp(i q.r)`

`Scc_norm(q,t) = |c2*rho1 - c1*rho2|^2 / (N*c1*c2)`

The unnormalized Bhatia–Thornton Scc uses denominator N. The extra c1*c2 normalization gives an independent randomly distributed particle reference of 1; it is not a general polymer mixing threshold. Reciprocal vectors are `2*pi*(nx/Lx,ny/Ly,nz/Lz)`. q=0 is excluded. Real-weight +/- directions have equal intensities and are not independent samples.

## Independent targets

- **q***: time-average S, then select the highest identifiable interior grid peak under declared prominence, competing-peak and block-consistency rules. No smoothing/interpolation is silently added.
- **M**: time-average normalized S, then `sum_b n_b*(Sbar_b-1)/sum_b n_b` over the declared band. n_b is the full direction count; M has lower bound -1.
- **Low-q mean**: time-average normalized S, then equal-weight the K complete exact shells in the declared band. No subtraction of 1. A coarse bin that mixes exact shells cannot reconstruct this definition and is rejected.

The default low-q band `(0,0.11]` includes five complete shells at approximately 0.0490873852, 0.0694200459, 0.0850218452, 0.0981747704, 0.1097627302. Direction counts are 6,12,8,6,24; each shell has final weight 1/5. This band is specific to the declared units and scale. The default M band is `(0,0.2]`; therefore its difference from the low-q mean reflects both weights and band, not independent information by construction.

The manifest next to each CSV supplies its exact checksum, normalization settings, box and shell geometry. Private original-source fields were removed by a field allowlist. Missing metadata are not fabricated; raw-source hashes/Drive identities are not distributed. The unchanged CSV checksum and retained geometry allow the computations in this package to be reproduced, not the original MD simulation.

## Model comparison

Each recipe is held out once; its complete row is excluded from fitting and scaling. All models share the folds. GPs are compared with a mean and ordinary linear model. Hyperparameters are optimized only on training rows; the final displayed curve is fitted on all five rows and is distinguished from held-out predictions. Gaussian standard deviations describe a new observed target conditional on fitted hyperparameters.

Five recipes with one seed each do not establish seed variability, a reliable calibration rate, a universal winning kernel or stage-3 prediction. Ten close frames and their two blocks are diagnostics, not additional independent training observations. Intrachain correlations may contribute to low-q signals; neither q* nor low-q magnitude alone establishes morphology/connectivity or phase separation. The proposed 20% run saving in a presentation is a future objective, not a measured result.

Changing target or kernel does not itself prove a simulation-time reduction. Cross-stage use requires paired stage data and independent validation. SANS/SAXS comparison additionally needs a confirmed bead/material mapping, appropriate contrast/form factors, units, instrument resolution and experimental corrections.

Formula background: [ISAACS partial-structure-factor documentation](https://isaacs.sourceforge.io/manual/page26_ct.html). The band definitions and target extraction rules are this project's declared operational choices.
