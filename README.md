# NACNormMode
This is a python code that projects cartesian NAC vectors onto the space of  vibrational normal modes. It also calculates the overall norm of the NAC both in cartesian and normal modes space as  $||d_{01}^{\xi}|| = \sqrt{\sum_{\xi}|d_{0I}^{\xi}|^2}$

The only ingredients needed to executed are Gaussian .log and .fchk files. The .log file can come from any TD calculation that inlcuded the 'NAC' keyword in the input file. The.fchk must be the formatted .chk of a 'freq' calculation. The cartesian coordinates of the structures of the two files MUST COINCIDE.

To run:
>> python3 nac_norm_modes.py --log NAC.log --fchk FREQ.fchk
