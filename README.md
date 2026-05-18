# NACNormMode
This is a python code that projects cartesian NAC vectors onto the space of  vibrational normal modes. 

The only ingredients needed to executed are Gaussian .log and .fchk files. The .log file can come from any TD calculation that inlcuded the 'NAC' keyword in the input file. The.fchk must be the formatted .chk of a 'freq' calculation. The cartesian coordinates of the structures of the two files MUST COINCIDE.

To run:
>> python3 nac_norm_modes.py --log NAC.log --fchk FREQ.fchk
